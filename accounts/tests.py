import os
import re
from unittest import mock

from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

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


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetTests(TestCase):
    def setUp(self):
        from accounts.models import CustomUser
        self.victim = CustomUser.objects.create_user('victim', 'victim@example.test', 'Old-pass-123!')

    def test_pages_render(self):
        self.assertEqual(self.client.get(reverse('accounts:password_reset')).status_code, 200)

    def test_requesting_a_reset_does_not_let_the_requester_change_the_password(self):
        r = self.client.post(reverse('accounts:password_reset'), {'email': 'victim@example.test'})
        self.assertEqual(r.status_code, 302)
        # The old attack: post a new password straight to the confirm step.
        for path in ('/accounts/password-reset/confirm/',
                     reverse('accounts:password_reset_confirm', args=['x', 'bad-token'])):
            self.client.post(path, {'new_password1': 'Hacked-pass-987!', 'new_password2': 'Hacked-pass-987!'})
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.check_password('Old-pass-123!'))

    def test_same_reply_for_unknown_email(self):
        a = self.client.post(reverse('accounts:password_reset'), {'email': 'victim@example.test'}, follow=True)
        b = self.client.post(reverse('accounts:password_reset'), {'email': 'nobody@example.test'}, follow=True)
        self.assertEqual([str(m) for m in a.context['messages']], [str(m) for m in b.context['messages']])
        self.assertEqual(len(mail.outbox), 1)

    def test_emailed_link_works_once(self):
        self.client.post(reverse('accounts:password_reset'), {'email': 'victim@example.test'})
        link = re.search(r'https?://\S+', mail.outbox[0].body).group(0)
        path = link.split('testserver', 1)[1]
        self.assertEqual(self.client.get(path).status_code, 200)
        r = self.client.post(path, {'new_password1': 'Brand-new-456!', 'new_password2': 'Brand-new-456!'})
        self.assertEqual(r.status_code, 302)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.check_password('Brand-new-456!'))
        # Used once: the token no longer matches the new password hash.
        self.assertEqual(self.client.get(path).status_code, 302)

    def test_weak_password_rejected(self):
        self.client.post(reverse('accounts:password_reset'), {'email': 'victim@example.test'})
        path = re.search(r'https?://\S+', mail.outbox[0].body).group(0).split('testserver', 1)[1]
        r = self.client.post(path, {'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(r.status_code, 200)
        self.victim.refresh_from_db()
        self.assertTrue(self.victim.check_password('Old-pass-123!'))


class CloudinaryUrlCleaningTests(SimpleTestCase):
    """A badly pasted CLOUDINARY_URL must never break the site."""

    def check(self, value):
        from PersonalPortfolio.storage import cloudinary_configured
        with mock.patch.dict(os.environ, {'CLOUDINARY_URL': value}):
            return cloudinary_configured(), os.environ['CLOUDINARY_URL']

    def test_good_value(self):
        self.assertEqual(self.check('cloudinary://1:abc@demo'), (True, 'cloudinary://1:abc@demo'))

    def test_pasted_with_name_spaces_or_quotes(self):
        for v in ('CLOUDINARY_URL=cloudinary://1:abc@demo', '  cloudinary://1:abc@demo ', '"cloudinary://1:abc@demo"'):
            self.assertEqual(self.check(v), (True, 'cloudinary://1:abc@demo'), v)

    def test_bad_value_falls_back_to_disk(self):
        for v in ('https://cloudinary.com/console', 'cloudinary://<your_api_key>', '427292211492217'):
            with mock.patch.dict(os.environ, {'CLOUDINARY_URL': v}):
                self.assertIs(image_storage(), default_storage, v)
