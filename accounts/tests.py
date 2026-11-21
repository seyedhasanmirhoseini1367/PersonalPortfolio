import os
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase

from PersonalPortfolio.storage import CloudinaryImageStorage, image_storage


class ImageStorageTests(SimpleTestCase):
    """Uploaded images go to Cloudinary when CLOUDINARY_URL is set."""

    def test_disk_without_cloudinary_url(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CLOUDINARY_URL', None)
            self.assertIs(image_storage(), default_storage)

    def test_cloudinary_with_url(self):
        with mock.patch.dict(os.environ, {'CLOUDINARY_URL': 'cloudinary://key:secret@demo'}):
            self.assertIsInstance(image_storage(), CloudinaryImageStorage)

    def test_names_are_unique_and_fit(self):
        s = CloudinaryImageStorage()
        a, b = s.get_available_name('profile_pics/me.JPG'), s.get_available_name('profile_pics/me.JPG')
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith('profile_pics/me_') and a.endswith('.jpg'))
        self.assertLessEqual(len(s.get_available_name('x/' + 'a' * 200 + '.png', max_length=100)), 100)

    @mock.patch('cloudinary.uploader.upload')
    def test_save_uploads_and_returns_name(self, upload):
        upload.return_value = {'public_id': 'profile_pics/me_1234abcd', 'format': 'png'}
        name = CloudinaryImageStorage().save('profile_pics/me.png', ContentFile(b'\x89PNG...', name='me.png'))
        self.assertEqual(name, 'profile_pics/me_1234abcd.png')
        kwargs = upload.call_args.kwargs
        self.assertEqual((kwargs['resource_type'], kwargs['overwrite']), ('image', False))
        self.assertTrue(kwargs['public_id'].startswith('profile_pics/me_'))

    def test_url(self):
        import cloudinary
        cloudinary.config(cloud_name='demo')
        url = CloudinaryImageStorage().url('profile_pics/me_1234abcd.png')
        self.assertTrue(url.startswith('https://res.cloudinary.com/demo/image/upload/'))
        self.assertTrue(url.endswith('/profile_pics/me_1234abcd.png'))
