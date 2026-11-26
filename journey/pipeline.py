"""Lesson pipeline: photos or text in, a draft lesson pack out.

  1. reader  - transcribes the lesson photos (Gemini vision; Groq vision as fallback),
               with a prompt from the group's subject
  2. subject - the group's subject agents turn the text into study items
               (see journey/subjects/; Finnish is the first and the default)
Then a person reviews the draft before it is published to the group.

The AI runs once per lesson. Review and games use the stored pack, so they cost nothing.
"""
import base64
import io
import logging
import os
import threading

from django.conf import settings
from django.db import close_old_connections, transaction

from . import subjects
from .models import LessonPack, Scene, StudyItem

logger = logging.getLogger(__name__)

MAX_IMAGES = 8
MAX_SIDE = 1600
MAX_SOURCE_CHARS = 18000


# ── 1. reader ────────────────────────────────────────────────────────────────

def prepare_image(raw: bytes) -> bytes:
    """Upright, shrink to MAX_SIDE and re-encode as JPEG: fewer tokens, less memory."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=85)
    return out.getvalue()


def _gemini_read(images, prompt):
    key = os.getenv('GEMINI_API_KEY', '')
    if not key:
        return None
    from google import genai
    from google.genai import types
    from content_generator.pipeline.config import GEMINI_MODEL
    client = genai.Client(api_key=key)
    parts = [types.Part.from_bytes(data=b, mime_type='image/jpeg') for b in images] + [prompt]
    resp = client.models.generate_content(
        model=GEMINI_MODEL, contents=parts,
        config=types.GenerateContentConfig(temperature=0.0,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return (resp.text or '').strip() or None


def _groq_read(images, prompt):
    key = os.getenv('GROQ_API_KEY', '')
    if not key:
        return None
    from groq import Groq
    model = os.getenv('JOURNEY_VISION_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
    content = [{'type': 'text', 'text': prompt}] + [
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(b).decode()}}
        for b in images[:5]]   # Groq accepts at most 5 images per request
    resp = Groq(api_key=key).chat.completions.create(
        model=model, messages=[{'role': 'user', 'content': content}], temperature=0.0, max_tokens=2048)
    return (resp.choices[0].message.content or '').strip() or None


def read_images(images, prompt=subjects.base.Subject.read_prompt):
    """Return the lesson text from the photos, or raise RuntimeError."""
    errors = []
    for reader in (_gemini_read, _groq_read):
        try:
            text = reader(images, prompt)
            if text:
                return text
        except Exception as exc:   # one provider failing should not stop the other
            errors.append(f'{reader.__name__}: {str(exc)[:160]}')
            logger.warning('LearningJourney reader failed: %s', exc)
    raise RuntimeError('Could not read the photos. ' + ('; '.join(errors) or 'No vision model is configured.'))


# ── run ──────────────────────────────────────────────────────────────────────

def _note(pack, note):
    pack.progress_note = note[:120]
    pack.save(update_fields=['progress_note'])


def build_pack(pack, images=(), text='', lookup=None):
    """Fill a pack with draft items. Leaves it DRAFT, or FAILED with an error message."""
    subject = subjects.get(pack.group.subject)
    try:
        parts = []
        if images:
            _note(pack, f'Reading {len(images)} photo(s)…')
            parts.append(read_images(list(images), subject.read_prompt))
        if text.strip():
            parts.append(text.strip())
        source = '\n\n'.join(p for p in parts if p).strip()
        if len(source) < 20:
            raise RuntimeError('There is too little text to build a lesson from.')
        pack.source_text = source[:MAX_SOURCE_CHARS]
        pack.save(update_fields=['source_text'])

        rows, summary = subject.build(source, lookup=lookup, note=lambda msg: _note(pack, msg))
        if not rows:
            raise RuntimeError('Nothing could be built from this text. Try clearer photos or paste the text.')
        scene_rows = _scene_rows(pack, source, subject, note=lambda msg: _note(pack, msg))
        with transaction.atomic():
            pack.items.all().delete()
            StudyItem.objects.bulk_create([StudyItem(pack=pack, **row) for row in rows])
            pack.scenes.all().delete()
            Scene.objects.bulk_create([Scene(pack=pack, **row) for row in scene_rows])
            pack.summary = summary
            pack.translations = {}
            pack.status = LessonPack.DRAFT
            pack.progress_note = ''
            pack.error = ''
            pack.save(update_fields=['summary', 'translations', 'status', 'progress_note', 'error'])
    except Exception as exc:
        logger.exception('LearningJourney pack %s failed', pack.pk)
        pack.status = LessonPack.FAILED
        pack.error = str(exc)[:1000]
        pack.progress_note = ''
        pack.save(update_fields=['status', 'error', 'progress_note'])
    return pack


def _scene_rows(pack, source, subject, note=lambda msg: None):
    """Role-play scenes from the subject's scene writer. A failure here never fails the lesson itself."""
    try:
        return subject.build_scenes(source, note=note) if source else []
    except Exception:
        logger.exception('LearningJourney scenes for pack %s failed', pack.pk)
        return []


def make_scenes(pack):
    """(Re)write the scenes of an existing lesson. Keeps the old ones if nothing valid comes back."""
    rows = _scene_rows(pack, pack.source_text, subjects.get(pack.group.subject))
    if rows:
        with transaction.atomic():
            pack.scenes.all().delete()
            Scene.objects.bulk_create([Scene(pack=pack, **row) for row in rows])
    return len(rows)


_scene_jobs = set()
_scene_lock = threading.Lock()


def start_scenes(pack):
    """Write scenes for an existing lesson in the background. Returns False if one is already running."""
    with _scene_lock:
        if pack.pk in _scene_jobs:
            return False
        _scene_jobs.add(pack.pk)

    def work(own_thread=True):
        try:
            make_scenes(LessonPack.objects.select_related('group').get(pk=pack.pk))
        finally:
            with _scene_lock:
                _scene_jobs.discard(pack.pk)
            if own_thread:
                close_old_connections()

    if getattr(settings, 'JOURNEY_RUN_INLINE', False):
        work(own_thread=False)
    else:
        threading.Thread(target=work, name=f'journey-scenes-{pack.pk}', daemon=True).start()
    return True


def scenes_running(pack):
    return pack.pk in _scene_jobs


def start(pack, images=(), text=''):
    """Build in a background thread (the site runs one web worker), or inline in tests."""
    if getattr(settings, 'JOURNEY_RUN_INLINE', False):
        return build_pack(pack, images, text)

    pack_id = pack.pk

    def work():
        try:
            build_pack(LessonPack.objects.select_related('group').get(pk=pack_id), images, text)
        finally:
            close_old_connections()

    threading.Thread(target=work, name=f'journey-pack-{pack_id}', daemon=True).start()
    return pack
