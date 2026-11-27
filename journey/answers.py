"""Server-side answer checking, so rewards never rest on what the browser says.

Mirrors the checks in templates/journey/review.html: the same normalising and the same "almost right"
spelling tolerance. The browser sends what the learner typed or picked; this decides if it was right.
"""
import re
import unicodedata

from .models import StudyItem

OK, CLOSE, WRONG = 'ok', 'close', 'no'
_PUNCT = re.compile(r'[.,!?;:"«»()]')


def norm(s):
    s = unicodedata.normalize('NFC', (s or '').lower()).replace('’', "'")
    return ' '.join(_PUNCT.sub('', s).split())


def distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _row(item, row):
    rows = (item.data or {}).get('rows', []) or []
    try:
        at = int(row)   # the index into the stored rows, as the practice page sends it
        r = rows[at] if at >= 0 else None
    except (TypeError, ValueError, IndexError):
        return None
    return r if isinstance(r, (list, tuple)) and len(r) > 1 else None


def expected(item, mode, row=None):
    """The accepted answers for a card in a practice mode, or [] when the server cannot tell."""
    data = item.data or {}
    if item.kind == StudyItem.TABLE:
        r = _row(item, row)
        return [r[1]] if r and r[1] else []
    if item.kind == StudyItem.QUESTION:
        options = data.get('options') or []
        at = data.get('answer', 0)
        return [options[at]] if isinstance(at, int) and 0 <= at < len(options) else []
    if mode == 'type':
        return {StudyItem.WORD: [item.front, item.form_in_text], StudyItem.PHRASE: [item.front],
                StudyItem.SENTENCE: [data.get('cloze', '')], StudyItem.CONCEPT: [item.front]}.get(item.kind, [])
    # multiple choice: which field the options are drawn from
    return {StudyItem.SENTENCE: [data.get('cloze', '')], StudyItem.PHRASE: [item.front],
            StudyItem.WORD: [item.meaning_en], StudyItem.CONCEPT: [item.meaning_en]}.get(item.kind, [])


def verify(item, mode, given, row=None):
    """OK, CLOSE (one or two letters off, typed only) or WRONG; None when the answer cannot be checked."""
    answers = [norm(a) for a in expected(item, mode, row) if a]
    if not answers:
        return None
    given = norm(given)
    if given and given in answers:
        return OK
    if mode == 'type' and given and any(len(a) >= 4 and distance(given, a) <= (2 if len(a) >= 8 else 1) for a in answers):
        return CLOSE
    return WRONG
