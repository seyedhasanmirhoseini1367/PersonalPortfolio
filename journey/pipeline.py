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
from django.db import models, transaction
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


# Vision models, tried in order. On the free tiers each model has its own quota, and models
# get retired, so several are listed; JOURNEY_GEMINI_VISION / JOURNEY_GROQ_VISION (comma-separated)
# replace the lists without a code change.
GEMINI_VISION = ['gemini-2.5-flash', 'gemini-flash-lite-latest', 'gemini-flash-latest', 'gemma-4-31b-it']
GROQ_VISION = ['qwen/qwen3.8-27b']


def _models(env, default):
    from content_generator.pipeline.config import GEMINI_MODEL
    names = [m.strip() for m in os.getenv(env, '').split(',') if m.strip()] or default
    if env == 'JOURNEY_GEMINI_VISION' and GEMINI_MODEL not in names:
        names = [GEMINI_MODEL] + names
    return list(dict.fromkeys(names))


def _gemini_read(blobs, prompt, mime='image/jpeg', model=None):
    key = os.getenv('GEMINI_API_KEY', '')
    if not key:
        return None
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    parts = [types.Part.from_bytes(data=b, mime_type=mime) for b in blobs] + [prompt]
    config = {'temperature': 0.0}
    if model.startswith('gemini-2.5'):
        config['thinking_config'] = types.ThinkingConfig(thinking_budget=0)
    resp = client.models.generate_content(model=model, contents=parts, config=types.GenerateContentConfig(**config))
    return (resp.text or '').strip() or None


def _groq_read(images, prompt, model=None):
    key = os.getenv('GROQ_API_KEY', '')
    if not key:
        return None
    import re
    from groq import Groq
    content = [{'type': 'text', 'text': prompt}] + [
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(b).decode()}}
        for b in images[:5]]   # Groq accepts at most 5 images per request
    resp = Groq(api_key=key).chat.completions.create(
        model=model, messages=[{'role': 'user', 'content': content}], temperature=0.0, max_tokens=4096)
    text = resp.choices[0].message.content or ''
    return re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip() or None


def _readers():
    return ([(f'gemini:{m}', lambda b, p, m=m: _gemini_read(b, p, model=m)) for m in _models('JOURNEY_GEMINI_VISION', GEMINI_VISION)] +
            [(f'groq:{m}', lambda b, p, m=m: _groq_read(b, p, model=m)) for m in _models('JOURNEY_GROQ_VISION', GROQ_VISION)])


def _busy(errors):
    return errors and all(any(c in e for c in ('429', '503', 'RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'rate')) for e in errors)


def read_images(images, prompt=subjects.base.Subject.read_prompt):
    """Return the text in the photos, or raise RuntimeError. Tries each vision model until one answers."""
    errors = []
    for name, reader in _readers():
        try:
            text = reader(images, prompt)
            if text:
                return text
        except Exception as exc:   # one model failing (quota, retired) should not stop the next
            errors.append(f'{name}: {str(exc)[:120]}')
            logger.warning('LearningJourney reader %s failed: %s', name, str(exc)[:200])
    if _busy(errors):
        raise RuntimeError('The AI services that read photos are busy or have used their free quota for now. '
                           'Wait a little and add the lesson again, or paste the text instead.')
    raise RuntimeError('Could not read the photos. ' + ('; '.join(errors)[:600] or 'No vision model is configured.'))


def read_pdf(data, prompt):
    """A scanned PDF: only Gemini models read PDFs directly."""
    errors = []
    for model in _models('JOURNEY_GEMINI_VISION', GEMINI_VISION):
        try:
            text = _gemini_read([data], prompt, mime='application/pdf', model=model)
            if text:
                return text
        except Exception as exc:
            errors.append(f'{model}: {str(exc)[:120]}')
    if _busy(errors):
        raise RuntimeError('The AI services that read scanned PDFs are busy or out of free quota for now. Try again later.')
    raise RuntimeError('This PDF has no text layer (it is a scan) and no vision model could read it. '
                       'Send the pages as photos instead.' + (f' ({"; ".join(errors)[:300]})' if errors else ''))


# ── build ────────────────────────────────────────────────────────────────────

def _note(pack, note):
    pack.progress_note = note[:120]
    pack.started_at = timezone.now()   # doubles as a heartbeat: the build is alive
    pack.save(update_fields=['progress_note', 'started_at'])


PHOTOS_PER_CALL = 4   # Groq takes at most 5 images per request; 4 keeps answers short enough


def read_photo_batches(images, prompt):
    """Read photos a few at a time, asking for a marker before each one so every part keeps its photo number."""
    parts = []
    for start in range(0, len(images), PHOTOS_PER_CALL):
        batch = images[start:start + PHOTOS_PER_CALL]
        if len(batch) == 1:
            parts.append((f'Photo {start + 1}', read_images(batch, prompt)))
            continue
        text = read_images(batch, prompt + f' There are {len(batch)} photos: start each one with a line '
                                           '"=== Photo N ===" (N = 1, 2, ...).')
        found = extract.split_marked(text, 'Photo')
        if len(found) == len(batch):
            parts += [(f'Photo {start + int(n)}', body) for n, body in found]
        else:   # the model ignored the markers: keep the text, with a label for the whole batch
            parts.append((f'Photos {start + 1}–{start + len(batch)}', extract.clean(text)))
    return parts


def _read_uploads(pack, subject):
    """Read the queued files (typed text is queued too, as a "text" upload) into labelled parts."""
    uploads = list(pack.uploads.all())
    others = [u for u in uploads if u.kind != 'text']
    documents = sum(1 for u in uploads if u.kind not in ('image', 'text'))
    parts, kinds, seen = [], set(), {}
    photos = [u for u in uploads if u.kind == 'image']
    if photos:   # several photos per AI call: far fewer requests against the free quotas
        _note(pack, f'Reading {len(photos)} photo(s)…')
        parts += read_photo_batches([bytes(u.data) for u in photos], subject.read_prompt)
        kinds.add('photos')
    rest = [u for u in uploads if u.kind != 'image']
    for n, up in enumerate(rest, 1):
        ex = extract.EXTRACTORS[up.kind]
        if up.kind == 'text':
            text = bytes(up.data).decode('utf-8')
            parts += [('Your text', text)] if others else ex.extract(text, 1, subject)
            kinds.add('text')
            continue
        _note(pack, f'Reading {up.name or ex.label} ({n} of {len(rest)})…')
        seen[up.kind] = seen.get(up.kind, 0) + 1
        found = ex.extract(bytes(up.data), seen[up.kind], subject)
        if documents > 1:
            found = [(f'{up.name[:28]} · {label}', text) for label, text in found]
        parts += found
        kinds.add(up.kind)
    return parts, kinds


def _attach(pack, parts, kinds, append):
    """Add the new parts to the lesson's text (after what it already has, when adding material).

    Returns only the new text: the AI builds items from what was just added.
    """
    source = pack.source_text if append else ''
    offsets = list(pack.source_parts or []) if append else []
    if append and len(source) >= MAX_SOURCE_CHARS - 200:
        raise RuntimeError('This lesson is full. Start a new lesson for more material.')
    today = timezone.localdate()
    prefix = f'{today.day} {today:%b} · ' if append else ''
    start = len(source) + (2 if source else 0)
    for label, text in parts:
        text = (text or '').strip()
        if not text:
            continue
        if source:
            source += '\n\n'
        offsets.append([(prefix + label)[:60], len(source)])
        source += text
    old_kind = pack.source_kind if append else ''
    if old_kind and old_kind not in kinds:
        kinds = kinds | {old_kind}
    with transaction.atomic():
        pack.source_text = source[:MAX_SOURCE_CHARS]
        pack.source_parts = [o for o in offsets if o[1] < MAX_SOURCE_CHARS]
        pack.source_kind = next(iter(kinds)) if len(kinds) == 1 else ('mixed' if kinds else 'text')
        pack.save(update_fields=['source_text', 'source_parts', 'source_kind'])
        pack.uploads.all().delete()   # originals are not kept
    return pack.source_text[start:]


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


# Practised kinds, in the order a duplicate is kept: a sentence beats a phrase with the same text, etc.
KEEP_ORDER = [StudyItem.WORD, StudyItem.CONCEPT, StudyItem.SENTENCE, StudyItem.PHRASE, StudyItem.QUESTION]


def drop_duplicates(rows, existing=()):
    """Remove practised items whose text repeats another one (any kind, any part of the material),
    including items the lesson already has from earlier material."""
    from .subjects.base import norm
    rank = {k: i for i, k in enumerate(KEEP_ORDER)}
    seen = {norm(front) for kind, front in existing if kind in rank}
    out = []
    for row in sorted(rows, key=lambda r: (rank.get(r['kind'], 99), r.get('order', 0))):
        if row['kind'] in rank:
            key = norm(row['front'])
            if key in seen:
                continue
            seen.add(key)
        out.append(row)
    return out


def _build(subject, source, lookup, note, context):
    kwargs = {'lookup': lookup, 'note': note}
    if 'context' in inspect.signature(subject.build).parameters:
        kwargs['context'] = context
    return subject.build(source, **kwargs)


def _fail(pack, message, had_items):
    """A lesson that already had items keeps them and its status; only a first build becomes FAILED."""
    if pack.uploads.exists() and not had_items:
        # The files could not all be read. They are deleted now, so a retry would build from the
        # typed text alone and silently miss the photos: clear the text so "Try again" asks for them.
        pack.source_text, pack.source_parts = '', []
        pack.save(update_fields=['source_text', 'source_parts'])
    pack.uploads.all().delete()
    if had_items:
        pack.status = LessonPack.PUBLISHED if pack.published_at else LessonPack.DRAFT
    else:
        pack.status = LessonPack.FAILED
    pack.error = str(message)[:1000]
    pack.progress_note = ''
    pack.save(update_fields=['status', 'error', 'progress_note'])


def build_pack(pack, lookup=None):
    """Build items from the lesson's new material.

    First build: the lesson becomes DRAFT (or FAILED with a reason).
    Adding material to a lesson that has items: new items are added after the old ones. A published
    lesson stays published: only the new items wait for a check (pending) and stay out of practice until
    then; old items and everyone's progress on them are untouched. If that fails, the lesson keeps its
    items and status, with the reason shown.
    """
    had_items = pack.items.exists()
    try:
        subject = subjects.get(pack.group.subject)   # an unknown subject fails the build, never falls back
        if pack.uploads.exists():
            parts, kinds = _read_uploads(pack, subject)
            new_text = _attach(pack, parts, kinds, append=had_items)
        elif not had_items:
            new_text = pack.source_text   # "Try again": the files were already read
        else:
            raise RuntimeError('Nothing new was added.')
        if len(new_text.strip()) < 20:
            raise RuntimeError('There is too little text to build a lesson from.')
        context = {'level': pack.group.level, 'focus': pack.focus}
        rows, summary = _build(subject, new_text, lookup, lambda msg: _note(pack, msg), context)
        existing = list(pack.items.values_list('kind', 'front'))
        rows = drop_duplicates(rows, existing)
        if not rows:
            raise RuntimeError('Everything in this material is already in the lesson.' if had_items else
                               'Nothing could be built from this material. Try clearer photos or paste the text.')
        rows = locate(pack, rows)
        published = had_items and pack.published_at is not None
        with transaction.atomic():
            if had_items:   # new items go after the old ones of the same kind
                last = {k: n for k, n in pack.items.values_list('kind').annotate(n=models.Max('order'))}
                for row in rows:
                    row['order'] = last.get(row['kind'], -1) + 1 + row.get('order', 0)
            else:
                pack.items.all().delete()
            StudyItem.objects.bulk_create([StudyItem(pack=pack, pending=published, **row) for row in rows])
            pack.summary = f'{pack.summary}\n\n{summary}'.strip() if had_items and summary else (summary or pack.summary)
            pack.translations = {}   # old translations are kept on their items; the new items are translated below
            pack.save(update_fields=['summary', 'translations'])
        _translate_now(pack)
        pack.status = LessonPack.PUBLISHED if published else LessonPack.DRAFT
        pack.progress_note = ''
        pack.error = ''
        pack.save(update_fields=['status', 'progress_note', 'error'])
    except Exception as exc:
        logger.exception('LearningJourney pack %s failed', pack.pk)
        _fail(pack, exc, had_items)
    return pack


# ── queue ────────────────────────────────────────────────────────────────────

def _translate_now(pack):
    """If the lesson's maker has a second language, translate the cards now, so Check opens with them ready.
    A failed translation never fails the lesson: the page tries again when it is opened."""
    from . import translate
    from .models import LearnerProfile
    lang = LearnerProfile.language_of(pack.created_by)
    if not lang or lang not in translate.HELPER_NAMES:
        return
    _note(pack, f'Translating into {translate.HELPER_NAMES[lang]}…')
    try:
        translate.translate_pack(pack, lang)
    except Exception:
        logger.exception('LearningJourney translation of pack %s to %s failed during the build', pack.pk, lang)


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

    files: [(kind, name, bytes)] from extract.Extractor.prepare. Works for a new lesson and for
    adding material to one that already has items.
    """
    files = list(files)
    if (text or '').strip():
        files.append(('text', 'Your text', text.strip()[:MAX_SOURCE_CHARS].encode('utf-8')))
    PendingUpload.objects.bulk_create([PendingUpload(pack=pack, order=i, kind=k, name=name[:160], data=data)
                                       for i, (k, name, data) in enumerate(files)])
    pack.status, pack.error, pack.started_at, pack.attempts = LessonPack.PROCESSING, '', None, 0
    pack.progress_note = 'Waiting for its turn…'
    pack.save(update_fields=['status', 'error', 'started_at', 'attempts', 'progress_note'])
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
            _fail(pack, 'Building this lesson was interrupted twice. Press “Try again”, or add it again.',
                  pack.items.exists())
            continue
        build_pack(pack)
        ran += 1
    return ran
