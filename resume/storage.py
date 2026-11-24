"""Database-backed storage for the CV PDF (survives Render deploys)."""
import mimetypes
import os
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.urls import reverse
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseFileStorage(Storage):
    def _model(self):
        from .models import StoredFile
        return StoredFile

    def get_available_name(self, name, max_length=None):
        base, ext = os.path.splitext(name.replace(chr(92), '/'))
        suffix = f'_{uuid.uuid4().hex[:6]}{ext.lower()}'
        if max_length is not None:
            base = base[:max(1, max_length - len(suffix))]
        return base + suffix

    def _save(self, name, content):
        if hasattr(content, 'seek'):
            content.seek(0)
        data = content.read()
        ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        self._model().objects.update_or_create(name=name, defaults={'data': data, 'content_type': ctype})
        return name

    def _open(self, name, mode='rb'):
        row = self._model().objects.filter(name=name).first()
        if row is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(row.data), name=name)

    def exists(self, name):
        return self._model().objects.filter(name=name).exists()

    def delete(self, name):
        self._model().objects.filter(name=name).delete()

    def size(self, name):
        row = self._model().objects.filter(name=name).first()
        return len(row.data) if row else 0

    def url(self, name):
        return reverse('resume:download_resume')


def cv_storage():
    return DatabaseFileStorage()
