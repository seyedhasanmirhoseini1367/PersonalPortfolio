"""Translator agent: adds a member's optional second language to a published lesson.

English is always there. A lesson is translated once per language, the first time
someone who chose that language opens it, and the result is shared by everyone in
the group with the same choice. So the cost grows with languages, not with members.
"""
import json
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction

from .models import HELPER_NAMES, LessonPack, StudyItem

logger = logging.getLogger(__name__)

CHUNK = 40
_running = set()
_lock = threading.Lock()

PROMPT = """Translate these English study notes for a learner of Finnish into {language}.
Keep Finnish words and sentences (in quotes or italics) exactly as they are. Keep it short and natural.
Return JSON only: {{"summary": "...", "items": [{{"id": 1, "meaning": "...", "body": "..."}}]}}
Give every id back. Leave "meaning" or "body" empty when the input has none.

{payload}
"""


def needed(pack, lang):
    return (bool(lang) and lang in HELPER_NAMES and pack.status in (LessonPack.DRAFT, LessonPack.PUBLISHED)
            and lang not in (pack.translations or {}))


def _ask(prompt):
    from content_generator.pipeline.agents.gemini_client import generate
    from content_generator.pipeline.config import GROQ_MODEL_LARGE
    data = json.loads(generate(prompt, model=GROQ_MODEL_LARGE) or '{}')
    return data if isinstance(data, dict) else {}


def translate_pack(pack, lang, ask=None):
    """Translate every item's English meaning and explanation, plus the summary. Saves and returns the pack."""
    ask = ask or _ask
    language = HELPER_NAMES[lang]
    # Only items without this language yet: a translation someone already corrected is kept.
    items = [i for i in pack.items.all() if (i.meaning_en or i.body) and not (i.translations or {}).get(lang)]
    summary, out = '', {}
    for start in range(0, max(len(items), 1), CHUNK):
        chunk = items[start:start + CHUNK]
        payload = {'items': [{'id': i.pk, 'meaning': i.meaning_en, 'body': i.body} for i in chunk]}
        if start == 0:
            payload['summary'] = pack.summary
        data = ask(PROMPT.format(language=language, payload=json.dumps(payload, ensure_ascii=False)))
        if start == 0:
            summary = str(data.get('summary') or '')[:1500]
        for row in data.get('items') or []:
            if isinstance(row, dict) and str(row.get('id', '')).isdigit():
                out[int(row['id'])] = {'meaning': str(row.get('meaning') or '')[:400],
                                       'body': str(row.get('body') or '')[:2000]}
    if items and not out:
        raise RuntimeError(f'The translator returned nothing for {language}.')
    with transaction.atomic():
        for item in items:
            if item.pk in out:
                item.translations = {**(item.translations or {}), lang: out[item.pk]}
                item.save(update_fields=['translations'])
        pack.translations = {**(pack.translations or {}), lang: summary}
        pack.save(update_fields=['translations'])
    return pack


def ensure(pack, lang):
    """Start a translation in the background if this lesson lacks the language. Returns True while one is pending."""
    if not needed(pack, lang):
        return False
    key = (pack.pk, lang)
    with _lock:
        if key in _running:
            return True
        _running.add(key)

    def work(own_thread=True):
        try:
            translate_pack(LessonPack.objects.get(pk=pack.pk), lang)
        except Exception:
            logger.exception('LearningJourney translation of pack %s to %s failed', pack.pk, lang)
        finally:
            with _lock:
                _running.discard(key)
            if own_thread:   # never close the connection of the request that called us
                close_old_connections()

    if getattr(settings, 'JOURNEY_RUN_INLINE', False):
        work(own_thread=False)
        pack.refresh_from_db()
        return needed(pack, lang)
    threading.Thread(target=work, name=f'journey-translate-{pack.pk}-{lang}', daemon=True).start()
    return True
