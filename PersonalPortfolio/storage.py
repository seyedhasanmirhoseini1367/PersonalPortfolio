"""Where uploaded images are stored.

Render's disk is wiped on every deploy, so images people upload (profile
pictures, story/project images, editor images) go to Cloudinary when
CLOUDINARY_URL is set. Without it (local development) they stay on disk.

Other uploads (trained models, RAG documents, PDFs) stay on the local disk
storage: the code reads them through a filesystem path.
"""
import logging
import os
import uuid

from django.core.files.storage import Storage, default_storage
from django.utils.deconstruct import deconstructible

logger = logging.getLogger(__name__)


@deconstructible
class CloudinaryImageStorage(Storage):
    """Minimal Django storage for images on Cloudinary.

    The stored name is "<folder>/<file>_<random>.<ext>"; the part before the
    extension is the Cloudinary public_id.
    """

    def get_available_name(self, name, max_length=None):
        base, ext = os.path.splitext(name.replace('\\', '/'))
        suffix = f'_{uuid.uuid4().hex[:8]}{ext.lower()}'
        if max_length is not None:
            base = base[:max(1, max_length - len(suffix))]
        return base + suffix

    def _save(self, name, content):
        import cloudinary.uploader

        base, ext = os.path.splitext(name)
        if hasattr(content, 'seek'):
            content.seek(0)
        result = cloudinary.uploader.upload(
            content, public_id=base, resource_type='image',
            overwrite=False, unique_filename=False, use_filename=False,
        )
        return f"{result['public_id']}.{result.get('format') or ext.lstrip('.')}"

    def exists(self, name):
        # Names are made unique in get_available_name.
        return False

    def url(self, name):
        import cloudinary

        base, ext = os.path.splitext(name)
        return cloudinary.CloudinaryImage(base).build_url(secure=True, format=ext.lstrip('.') or None)

    def delete(self, name):
        import cloudinary.uploader

        if name:
            cloudinary.uploader.destroy(os.path.splitext(name)[0], resource_type='image')

    def size(self, name):
        raise NotImplementedError('Size is not tracked for Cloudinary images.')


def cloudinary_configured() -> bool:
    """True when CLOUDINARY_URL holds a usable value.

    Tolerates common copy-paste slips (surrounding spaces or quotes, or the
    whole "CLOUDINARY_URL=cloudinary://..." line pasted as the value) by
    cleaning the variable before the cloudinary package reads it. A value
    that is still wrong is logged and ignored, so a bad setting can never
    take the site down (it did once: every page raised ValueError).
    """
    raw = os.environ.get('CLOUDINARY_URL', '')
    value = raw.strip().strip('"\'').strip()
    if value.upper().startswith('CLOUDINARY_URL='):
        value = value.split('=', 1)[1].strip().strip('"\'').strip()
    if not value:
        return False
    if not (value.startswith('cloudinary://') and '@' in value and ':' in value[len('cloudinary://'):]):
        logger.error('CLOUDINARY_URL is set but is not "cloudinary://<key>:<secret>@<cloud>"; '
                     'uploaded images stay on local disk until it is fixed.')
        return False
    if value != raw:
        os.environ['CLOUDINARY_URL'] = value
    return True


def image_storage():
    """Storage for uploaded images: Cloudinary in production, disk locally."""
    if cloudinary_configured():
        return CloudinaryImageStorage()
    return default_storage
