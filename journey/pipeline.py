"""Lesson pipeline: material in (text, photos, PDF, Word), a draft lesson out.

  1. queue    - the request stores the checked files (PendingUpload) and marks the pack
                PROCESSING; the site's background worker builds it (run_pending), so a
                restart does not lose it: an interrupted build is taken again once
  2. extract  - one extractor per file kind (journey/extract.py) gives labelled parts,
                e.g. "Photo 2", "Page 5", "Paragraph 3"; the files are deleted right after
  3. subject  - the space's subject agents turn the text into study items
                (journey/subjects/: Finnish, and general subjects)
  4. locate   - each item gets the label of the part it came from
Then the learner checks the draft before it is published.

The AI runs once per lesson. Review uses the stored items, so it costs nothing.
"""
import base64
import inspect
import io
import logging
import os
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import extract, subjects
from .models import LessonPack, PendingUpload, StudyItem

logger = logging.getLogger(__name__)

MAX_IMAGES = 8
MAX_FILES = 8
MAX_SIDE = 1600
MAX_SOURCE_CHARS = 40000
STALE_AFTER = timedelta(minutes=15)   # a build with no news for this long was interrupted
MAX_ATTEMPTS = 2


# ── readers ──────────────────────────────────────────────────────────────────

def prepare_image(raw: bytes) -> bytes:
    """Upright, shrink to MAX_SIDE and re-encode as JPEG: fewer tokens, less memory."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert('RGB')
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=85)
    return out.getvalue()


def _gemini_read(blobs, prompt, mime='image/jpeg'):
    key = os.getenv('GEMINI_API_KEY', '')
    if not key:
        return None
    from google import genai
    from google.genai import types
    from content_generator.pipeline.config import GEMINI_MODEL
    client = genai.Client(api_key=key)
    parts = [types.Part.from_bytes(data=b, mime_type=mime) for b in blobs] + [prompt]
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
    """Return the text in the photos, or raise RuntimeError."""
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


def read_pdf(data, prompt):
    """A scanned PDF: only Gemini reads PDFs directly."""
    try:
        text = _gemini_read([data], prompt, mime='application/pdf')
    except Exception as exc:
        raise RuntimeError(f'Could not read the scanned PDF: {str(exc)[:160]}')
    if not text:
        raise RuntimeError('This PDF has no text layer (it is a scan) and no vision model could read it. '
                           'Send the pages as photos instead.')
    return text


# ── build ────────────────────────────────────────────────────────────────────

def _note(pack, note):
    pack.progress_note = note[:120]
    pack.started_at = timezone.now()   # doubles as a heartbeat: the build is alive
    pack.save(update_fields=['progress_note', 'started_at'])


def _gather(pack, subject):
    """Read every queued file into labelled parts, add the typed text, then drop the files."""
    uploads = list(pack.uploads.all())
    documents = sum(1 for u in uploads if u.kind != 'image')
    parts, kinds, seen = [], set(), {}
    for n, up in enumerate(uploads, 1):
        ex = extract.EXTRACTORS[up.kind]
        _note(pack, f'Reading {up.name or ex.label} ({n} of {len(uploads)})…')
        seen[up.kind] = seen.get(up.kind, 0) + 1
        found = ex.extract(bytes(up.data), seen[up.kind], subject)
        if documents > 1 and up.kind != 'image':
            found = [(f'{up.name[:28]} · {label}', text) for label, text in found]
        parts += found
        kinds.add('photos' if up.kind == 'image' else up.kind)
    typed = pack.source_text.strip()
    if typed:
        parts += [('Your text', typed)] if uploads else extract.EXTRACTORS['text'].extract(typed, 1, subject)
        kinds.add('text')
    source, offsets = '', []
    for label, text in parts:
        text = (text or '').strip()
        if not text:
            continue
        if source:
            source += '\n\n'
        offsets.append([label[:60], len(source)])
        source += text
    with transaction.atomic():
        pack.source_text = source[:MAX_SOURCE_CHARS]
        pack.source_parts = [o for o in offsets if o[1] < MAX_SOURCE_CHARS]
        pack.source_kind = next(iter(kinds)) if len(kinds) == 1 else ('mixed' if kinds else 'text')
        pack.save(update_fields=['source_text', 'source_parts', 'source_kind'])
        pack.uploads.all().delete()   # originals are not kept
    return pack.source_text


def locate(pack, rows):
    """Give each item the label of the part its text was found in (only useful with several parts)."""
    if len(pack.source_parts or []) < 2:
        return rows
    # Compare with whitespace collapsed (PDF text breaks lines anywhere), keeping a map back to the original offsets.
    flat, where = [], []
    for i, ch in enumerate(pack.source_text.lower()):
        if ch.isspace():
            if flat and flat[-1] == ' ':
                continue
            ch = ' '
        flat.append(ch)
        where.append(i)
    flat = ''.join(flat)
    for row in rows:
        data = row.get('data') or {}
        for snippet in (data.get('quote'), row.get('example'), row.get('form_in_text'), row.get('front')):
            snippet = ' '.join((snippet or '').lower().split())
            at = flat.find(snippet) if len(snippet) >= 3 else -1
            if at >= 0:
                row['source_ref'] = pack.part_at(where[at])[:60]
                break
    return rows


def _build(subject, source, lookup, note, context):
    kwargs = {'lookup': lookup, 'note': note}
    if 'context' in inspect.signature(subject.build).parameters:
        kwargs['context'] = context
    return subject.build(source, **kwargs)


def build_pack(pack, lookup=None):
    """Fill a pack with draft items. Leaves it DRAFT, or FAILED with an error message."""
    subject = subjects.get(pack.group.subject)
    try:
        if pack.uploads.exists() or not pack.source_parts:
            source = _gather(pack, subject)
        else:
            source = pack.source_text   # a retry: the files were already read
        if len(source) < 20:
            raise RuntimeError('There is too little text to build a lesson from.')
        context = {'level': pack.group.level, 'focus': pack.focus}
        rows, summary = _build(subject, source, lookup, lambda msg: _note(pack, msg), context)
        if not rows:
            raise RuntimeError('Nothing could be built from this material. Try clearer photos or paste the text.')
        rows = locate(pack, rows)
        with transaction.atomic():
            pack.items.all().delete()
            StudyItem.objects.bulk_create([StudyItem(pack=pack, **row) for row in rows])
            pack.summary = summary
            pack.translations = {}
            pack.status = LessonPack.DRAFT
            pack.progress_note = ''
            pack.error = ''
            pack.save(update_fields=['summary', 'translations', 'status', 'progress_note', 'error'])
    except Exception as exc:
        logger.exception('LearningJourney pack %s failed', pack.pk)
        pack.uploads.all().delete()
        pack.status = LessonPack.FAILED
        pack.error = str(exc)[:1000]
        pack.progress_note = ''
        pack.save(update_fields=['status', 'error', 'progress_note'])
    return pack


# ── queue ────────────────────────────────────────────────────────────────────

def _wake_worker():
    if getattr(settings, 'JOURNEY_RUN_INLINE', False):
        run_pending()
        return
    try:
        from content_generator import worker
        worker.wake()
    except Exception:
        logger.warning('LearningJourney could not wake the worker; it picks the lesson up on its next round')


def queue(pack, files=(), text=''):
    """Store the checked files and the typed text, then hand the build to the background worker.

    files: [(kind, name, bytes)] from extract.Extractor.prepare.
    """
    PendingUpload.objects.bulk_create([PendingUpload(pack=pack, order=i, kind=k, name=name[:160], data=data)
                                       for i, (k, name, data) in enumerate(files)])
    pack.source_text = (text or '').strip()[:MAX_SOURCE_CHARS]
    pack.source_parts = []
    pack.status, pack.error, pack.started_at, pack.attempts = LessonPack.PROCESSING, '', None, 0
    pack.progress_note = 'Waiting for its turn…'
    pack.save(update_fields=['source_text', 'source_parts', 'status', 'error', 'started_at', 'attempts', 'progress_note'])
    _wake_worker()
    pack.refresh_from_db()
    return pack


def retry(pack):
    """Build again from the text that was already read (the files are not kept)."""
    pack.status, pack.error, pack.attempts, pack.started_at = LessonPack.PROCESSING, '', 0, None
    pack.progress_note = 'Starting again…'
    pack.save(update_fields=['status', 'error', 'attempts', 'started_at', 'progress_note'])
    _wake_worker()


def run_pending(limit=3):
    """Called by the background worker: build waiting lessons, oldest first. Returns how many were built."""
    ran = 0
    for _ in range(limit):
        now = timezone.now()
        free = Q(started_at__isnull=True) | Q(started_at__lt=now - STALE_AFTER)
        pk = (LessonPack.objects.filter(status=LessonPack.PROCESSING).filter(free)
              .order_by('created_at').values_list('pk', flat=True).first())
        if pk is None:
            break
        # Claim it; if another process claimed it first, the update matches nothing.
        if not LessonPack.objects.filter(pk=pk, status=LessonPack.PROCESSING).filter(free).update(
                started_at=now, attempts=F('attempts') + 1):
            continue
        pack = LessonPack.objects.select_related('group').get(pk=pk)
        if pack.attempts > MAX_ATTEMPTS:
            pack.uploads.all().delete()
            pack.status, pack.progress_note = LessonPack.FAILED, ''
            pack.error = 'Building this lesson was interrupted twice. Press “Try again”, or add it again.'
            pack.save(update_fields=['status', 'progress_note', 'error'])
            continue
        build_pack(pack)
        ran += 1
    return ran
