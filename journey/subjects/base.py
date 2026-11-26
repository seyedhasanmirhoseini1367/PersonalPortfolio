"""Subjects: what the AI builds from a lesson, per kind of class.

A study group has one subject. The shared parts of LearningJourney (upload, reading
photos, draft review, daily review, mistakes, second language, groups) work for every
subject; a subject only decides which agents turn the lesson text into study items.

To add a subject: subclass Subject, implement build(), and register it in __init__.py.
"""
import json
import re


class Subject:
    key = ''
    name = ''
    description = ''
    speech_lang = ''          # BCP-47 tag for the browser's text-to-speech; '' turns speech off
    read_prompt = ('These photos are pages from a lesson (textbook, handout or whiteboard), in order. '
                   'Transcribe all the text exactly as written, page by page, keeping line breaks. '
                   'Do not translate, explain or correct anything. If a word is unreadable, write [?]. '
                   'Return only the transcribed text.')
    title_placeholder = 'Lesson 1'
    text_placeholder = ''

    def build(self, source, lookup=None, note=lambda msg: None):
        """Turn the lesson text into (items, summary).

        items is a list of dicts with StudyItem fields (kind, order, front, meaning_en, ...).
        Raise RuntimeError with a readable message when nothing useful can be built.
        """
        raise NotImplementedError


# ── shared helpers for agents ────────────────────────────────────────────────

def ask_json(prompt):
    from content_generator.pipeline.agents.gemini_client import generate
    from content_generator.pipeline.config import GROQ_MODEL_LARGE
    raw = generate(prompt, model=GROQ_MODEL_LARGE)
    data = json.loads(raw) if raw else {}
    return data if isinstance(data, dict) else {}


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
