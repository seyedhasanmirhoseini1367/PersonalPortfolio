"""Lesson pipeline: photos or text in, a draft lesson pack out.

Agents, in order:
  1. reader     - transcribes the lesson photos (Gemini vision; Groq vision as fallback)
  2. linguist   - words with base forms, cases and meanings; sentences for cloze cards
  3. teacher    - lesson summary, grammar notes, useful phrases, questions, verb tables
  4. checker    - looks each base form up on Wiktionary and grades confidence
  5. quality    - drops anything not grounded in the lesson text or with a broken answer
Then a person reviews the draft before it is published to the group.

The AI runs once per lesson. Review and games use the stored pack, so they cost nothing.
"""
import base64
import io
import json
import logging
import os
import re
import threading
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import close_old_connections, transaction

from .models import LessonPack, StudyItem

logger = logging.getLogger(__name__)

MAX_IMAGES = 8
MAX_SIDE = 1600
MAX_TEXT_CHARS = 9000
MAX_WORDS = 40
MAX_LOOKUPS = 45
WIKTIONARY = 'https://en.wiktionary.org/api/rest_v1/page/definition/'
HEADERS = {'User-Agent': 'LearningJourney/1.0 (study app; contact via site)'}


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


READ_PROMPT = (
    'These photos are pages from a Finnish language lesson (textbook, handout or whiteboard), in order. '
    'Transcribe all the Finnish text exactly as written, page by page, keeping line breaks and punctuation. '
    'Do not translate, explain or correct anything. Leave out page numbers and decorations. '
    'If a word is unreadable, write [?]. Return only the transcribed text.'
)


def _gemini_read(images):
    key = os.getenv('GEMINI_API_KEY', '')
    if not key:
        return None
    from google import genai
    from google.genai import types
    from content_generator.pipeline.config import GEMINI_MODEL
    client = genai.Client(api_key=key)
    parts = [types.Part.from_bytes(data=b, mime_type='image/jpeg') for b in images] + [READ_PROMPT]
    resp = client.models.generate_content(
        model=GEMINI_MODEL, contents=parts,
        config=types.GenerateContentConfig(temperature=0.0,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return (resp.text or '').strip() or None


def _groq_read(images):
    key = os.getenv('GROQ_API_KEY', '')
    if not key:
        return None
    from groq import Groq
    model = os.getenv('JOURNEY_VISION_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
    content = [{'type': 'text', 'text': READ_PROMPT}] + [
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(b).decode()}}
        for b in images[:5]]   # Groq accepts at most 5 images per request
    resp = Groq(api_key=key).chat.completions.create(
        model=model, messages=[{'role': 'user', 'content': content}], temperature=0.0, max_tokens=2048)
    return (resp.choices[0].message.content or '').strip() or None


def read_images(images):
    """Return the lesson text from the photos, or raise RuntimeError."""
    errors = []
    for reader in (_gemini_read, _groq_read):
        try:
            text = reader(images)
            if text:
                return text
        except Exception as exc:   # one provider failing should not stop the other
            errors.append(f'{reader.__name__}: {str(exc)[:160]}')
            logger.warning('LearningJourney reader failed: %s', exc)
    raise RuntimeError('Could not read the photos. ' + ('; '.join(errors) or 'No vision model is configured.'))


# ── 2 + 3. linguist and teacher ─────────────────────────────────────────────

LINGUIST_PROMPT = """You help an A1-A2 learner of Finnish who reads English.
From the lesson text below, return JSON only:
{{
 "words": [{{"lemma": "dictionary base form (nominative singular, or first infinitive for verbs)",
            "form_in_text": "the exact form used in the text",
            "pos": "noun|verb|adjective|adverb|pronoun|other",
            "grammar": "short label, e.g. 'inessiivi (in)', 'partitiivi', 'verbityyppi 1', 'k:∅ astevaihtelu'",
            "meaning_en": "English meaning in this text",
            "example": "one sentence copied exactly from the text"}}],
 "sentences": [{{"sentence": "a useful sentence copied exactly from the text",
                "cloze": "one word of that sentence to hide",
                "meaning_en": "English translation"}}]
}}
Rules: at most {max_words} of the most useful words, no names or numbers, no duplicates.
Copy "example" and "sentence" character for character from the text. At most 12 sentences.

LESSON TEXT:
{text}
"""

TEACHER_PROMPT = """You are a Finnish teacher for an A1-A2 learner who reads English.
From the lesson text below, return JSON only:
{{
 "summary_en": "3-4 plain English sentences: what this lesson teaches (topic, key words, grammar)",
 "grammar": [{{"title": "e.g. Inessiivi: -ssa / -ssä", "explanation_en": "a short, simple explanation in English",
              "examples": ["sentences copied exactly from the text"]}}],
 "phrases": [{{"fi": "a ready-to-use Finnish phrase from or based on the text", "meaning_en": "..."}}],
 "questions": [{{"question": "a simple comprehension question in Finnish", "question_en": "the same in English",
                "options": ["four short Finnish answers"], "answer": 0, "explanation_en": "why, in English"}}],
 "tables": [{{"lemma": "an important verb from the text (first infinitive)", "meaning_en": "...",
             "rows": [["minä", "..."], ["sinä", "..."], ["hän", "..."], ["me", "..."], ["te", "..."], ["he", "..."]]}}]
}}
Rules: at most 4 grammar notes, 10 phrases, 5 questions (answerable from the text, exactly one correct option,
"answer" is its index 0-3) and 3 verb tables in the present tense. Use only grammar that appears in the text.

LESSON TEXT:
{text}
"""


def _ask(prompt):
    from content_generator.pipeline.agents.gemini_client import generate
    from content_generator.pipeline.config import GROQ_MODEL_LARGE
    raw = generate(prompt, model=GROQ_MODEL_LARGE)
    data = json.loads(raw) if raw else {}
    return data if isinstance(data, dict) else {}


def linguist(text):
    return _ask(LINGUIST_PROMPT.format(text=text[:MAX_TEXT_CHARS], max_words=MAX_WORDS))


def teacher(text):
    return _ask(TEACHER_PROMPT.format(text=text[:MAX_TEXT_CHARS]))


# ── 5. quality: keep only what the lesson text supports ─────────────────────

def norm(s):
    s = (s or '').lower().replace('’', "'").replace('–', '-')
    return re.sub(r'\s+', ' ', s).strip(' .,!?;:"\'«»()')


def in_text(fragment, text):
    f = norm(fragment)
    return bool(f) and f in norm(text)


def word_in(word, text):
    w = norm(word)
    return bool(w) and re.search(r'(?<![\w-])' + re.escape(w) + r'(?![\w-])', norm(text)) is not None


def _s(v, limit=300):
    return str(v or '').strip()[:limit]


def clean_words(words, text):
    out, seen = [], set()
    for w in words or []:
        if not isinstance(w, dict):
            continue
        lemma = _s(w.get('lemma'), 120)
        key = lemma.lower()
        if not lemma or key in seen or re.search(r'\d', lemma):
            continue
        seen.add(key)
        form = _s(w.get('form_in_text'), 120)
        example = _s(w.get('example'), 400)
        out.append(dict(
            lemma=lemma, form_in_text=form if form.lower() != key else '',
            pos=_s(w.get('pos'), 20), grammar=_s(w.get('grammar'), 160),
            meaning_en=_s(w.get('meaning_en'), 400),
            example=example if in_text(example, text) else '',
            # A form the text does not contain means the model misread or invented it.
            grounded=word_in(form or lemma, text)))
    return out[:MAX_WORDS]


def clean_sentences(sentences, text):
    out, seen = [], set()
    for s in sentences or []:
        if not isinstance(s, dict):
            continue
        sentence, cloze = _s(s.get('sentence'), 300), _s(s.get('cloze'), 60)
        if not in_text(sentence, text) or not word_in(cloze, sentence) or norm(sentence) in seen:
            continue
        seen.add(norm(sentence))
        out.append(dict(sentence=sentence, cloze=cloze, meaning_en=_s(s.get('meaning_en'), 400)))
    return out[:12]


def clean_questions(questions):
    out = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        options = [_s(o, 120) for o in (q.get('options') or [])]
        try:
            answer = int(q.get('answer'))
        except (TypeError, ValueError):
            continue
        if (len(options) != 4 or not all(options) or len({o.lower() for o in options}) != 4
                or not 0 <= answer < 4 or not _s(q.get('question'))):
            continue
        out.append(dict(question=_s(q.get('question')), question_en=_s(q.get('question_en')),
                        options=options, answer=answer, explanation_en=_s(q.get('explanation_en'), 600)))
    return out[:5]


def clean_grammar(notes, text):
    out = []
    for g in notes or []:
        if not isinstance(g, dict) or not _s(g.get('title')):
            continue
        examples = [_s(e, 300) for e in (g.get('examples') or []) if in_text(e, text)]
        out.append(dict(title=_s(g.get('title'), 160), explanation_en=_s(g.get('explanation_en'), 1500),
                        examples=examples[:4]))
    return out[:4]


def clean_phrases(phrases):
    out, seen = [], set()
    for p in phrases or []:
        if not isinstance(p, dict):
            continue
        fi = _s(p.get('fi'), 200)
        if fi and fi.lower() not in seen:
            seen.add(fi.lower())
            out.append(dict(fi=fi, meaning_en=_s(p.get('meaning_en'), 400)))
    return out[:10]


def clean_tables(tables, text):
    out = []
    for t in tables or []:
        if not isinstance(t, dict) or not _s(t.get('lemma')):
            continue
        rows = [[_s(r[0], 20), _s(r[1], 60)] for r in (t.get('rows') or [])
                if isinstance(r, (list, tuple)) and len(r) == 2 and _s(r[0]) and _s(r[1])]
        if len(rows) == 6:
            out.append(dict(lemma=_s(t.get('lemma'), 60), meaning_en=_s(t.get('meaning_en'), 120), rows=rows))
    return out[:3]


# ── 4. checker ───────────────────────────────────────────────────────────────

def _strip_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()


def wiktionary_lookup(lemma, session=None):
    """Return (found_in_finnish, first_english_definition). Network errors count as not checked."""
    http = session or requests
    try:
        r = http.get(WIKTIONARY + quote(lemma.replace(' ', '_')), headers=HEADERS, timeout=8)
    except requests.RequestException:
        return None, ''
    if r.status_code == 404:
        return False, ''
    if r.status_code != 200:
        return None, ''
    entries = (r.json() or {}).get('fi') or []
    for entry in entries:
        for d in entry.get('definitions') or []:
            text = _strip_html(d.get('definition'))
            if text:
                return True, text[:200]
    return bool(entries), ''


def check_words(words, lookup=None):
    """Grade each word: high = found on Wiktionary as Finnish and in the text; low = not in the text."""
    lookup = lookup or wiktionary_lookup
    session = requests.Session()
    for i, w in enumerate(words):
        found, definition = (lookup(w['lemma'], session) if i < MAX_LOOKUPS else (None, ''))
        if not w['meaning_en'] and definition:
            w['meaning_en'] = definition
        if not w['grounded']:
            w['confidence'] = StudyItem.LOW
        elif found:
            w['confidence'] = StudyItem.HIGH
        elif found is False:
            w['confidence'] = StudyItem.LOW
        else:
            w['confidence'] = StudyItem.MEDIUM
    return words


# ── run ──────────────────────────────────────────────────────────────────────

def _note(pack, note):
    pack.progress_note = note[:120]
    pack.save(update_fields=['progress_note'])


def build_pack(pack, images=(), text='', lookup=None):
    """Fill a pack with draft items. Leaves it DRAFT, or FAILED with an error message."""
    try:
        parts = []
        if images:
            _note(pack, f'Reading {len(images)} photo(s)…')
            parts.append(read_images(list(images)))
        if text.strip():
            parts.append(text.strip())
        source = '\n\n'.join(p for p in parts if p).strip()
        if len(source) < 20:
            raise RuntimeError('There is too little text to build a lesson from.')
        pack.source_text = source[:MAX_TEXT_CHARS * 2]
        pack.save(update_fields=['source_text'])

        _note(pack, 'Finding words and sentences…')
        ling = linguist(source)
        _note(pack, 'Writing grammar notes, phrases and questions…')
        teach = teacher(source)

        words = clean_words(ling.get('words'), source)
        _note(pack, f'Checking {len(words)} words on Wiktionary…')
        words = check_words(words, lookup)
        sentences = clean_sentences(ling.get('sentences'), source)
        grammar = clean_grammar(teach.get('grammar'), source)
        phrases = clean_phrases(teach.get('phrases'))
        questions = clean_questions(teach.get('questions'))
        tables = clean_tables(teach.get('tables'), source)
        if not words and not sentences:
            raise RuntimeError('The AI found no words or sentences in this text. Try clearer photos or paste the text.')

        items = []
        for i, w in enumerate(words):
            label = ' · '.join(x for x in (w['pos'], w['grammar']) if x)
            items.append(StudyItem(pack=pack, kind=StudyItem.WORD, order=i, front=w['lemma'],
                                   form_in_text=w['form_in_text'], grammar=label[:160],
                                   meaning_en=w['meaning_en'], example=w['example'], confidence=w['confidence']))
        for i, s in enumerate(sentences):
            items.append(StudyItem(pack=pack, kind=StudyItem.SENTENCE, order=i, front=s['sentence'],
                                   meaning_en=s['meaning_en'], data={'cloze': s['cloze']}, confidence=StudyItem.HIGH))
        for i, p in enumerate(phrases):
            items.append(StudyItem(pack=pack, kind=StudyItem.PHRASE, order=i, front=p['fi'], meaning_en=p['meaning_en']))
        for i, g in enumerate(grammar):
            items.append(StudyItem(pack=pack, kind=StudyItem.GRAMMAR, order=i, front=g['title'],
                                   body=g['explanation_en'], data={'examples': g['examples']}))
        for i, q in enumerate(questions):
            items.append(StudyItem(pack=pack, kind=StudyItem.QUESTION, order=i, front=q['question'],
                                   meaning_en=q['question_en'], body=q['explanation_en'],
                                   data={'options': q['options'], 'answer': q['answer']}))
        for i, t in enumerate(tables):
            items.append(StudyItem(pack=pack, kind=StudyItem.TABLE, order=i, front=t['lemma'],
                                   meaning_en=t['meaning_en'], data={'rows': t['rows']}))
        with transaction.atomic():
            pack.items.all().delete()
            StudyItem.objects.bulk_create(items)
            pack.summary = _s(teach.get('summary_en'), 1500)
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


def start(pack, images=(), text=''):
    """Build in a background thread (the site runs one web worker), or inline in tests."""
    if getattr(settings, 'JOURNEY_RUN_INLINE', False):
        return build_pack(pack, images, text)

    pack_id = pack.pk

    def work():
        try:
            build_pack(LessonPack.objects.get(pk=pack_id), images, text)
        finally:
            close_old_connections()

    threading.Thread(target=work, name=f'journey-pack-{pack_id}', daemon=True).start()
    return pack
