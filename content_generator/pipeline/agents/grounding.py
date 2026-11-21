"""Keep generated content to facts that exist in the source material.

Two parts:
- GROUNDING_RULES: the instruction every writing prompt carries.
- check_and_clean(): a deterministic pass over the finished text. Every
  numeric claim (percentages, multipliers, money, "500 customers",
  "10 years", ratings, "1 in 3") whose number does not appear in the
  sources is replaced with an [ADD STAT] placeholder, and invented
  attributions ("studies show", "according to a report") and quotes that
  are not in the sources are reported for review.
"""
import re

PLACEHOLDER = '[ADD STAT]'

GROUNDING_RULES = """FACTS RULES (strict — breaking them makes the content unusable):
- Use ONLY facts found in COMPANY FACTS below (and the goal/keywords). Never invent numbers,
  percentages, prices, customer counts, years in business, ratings, results, studies, surveys,
  reports, research findings, awards, certifications, partner or customer names, or quotes.
- Do not write "studies show", "research shows", "according to ...", "experts say" or similar
  unless the exact source is in COMPANY FACTS.
- Where a figure would make a point stronger but none is given, write the placeholder
  [ADD STAT] (optionally followed by what to measure, e.g. "[ADD STAT] fewer support calls")
  so a human fills it in. Never replace a placeholder with a made-up number.
- Prefer concrete, verifiable statements about what the product does over impressive claims."""

_NUM = r'\d+(?:[.,]\d+)*'
_ENTITY = (r'customers?|clients?|users?|patients?|companies|company|businesses|organi[sz]ations?|'
           r'employees?|experts?|doctors?|clinicians?|countries|cities|reviews?|downloads?|members?|'
           r'partners?|projects?|hospitals?|clinics?|teams?|installs?|subscribers?|people|families|'
           r'asiakasta|käyttäjää|potilasta|yritystä')
CLAIM_PATTERNS = [
    rf'{_NUM}\s?(?:%|percent\b|per cent\b|prosenttia\b)',                     # 40%, 40 percent
    rf'\b{_NUM}\s?(?:x|×)(?=[\s,.!?)]|$)',                                     # 3x
    rf'\b{_NUM}\s+times\s+(?:faster|more|better|cheaper|less|higher|lower)',   # 3 times faster
    rf'[€$£]\s?{_NUM}(?:\s?(?:k|m|bn|million|billion|thousand))?',             # €20, $1.5m
    rf'\b{_NUM}\s?(?:€|eur\b|euros?\b|usd\b|dollars?\b)',                      # 20 €
    rf'\b{_NUM}\s?(?:k|thousand|million|billion|miljoonaa|tuhatta)\b',         # 10k, 2 million
    rf'\b{_NUM}\s+(?:out of|in)\s+{_NUM}\b',                                   # 1 in 3, 4 out of 5
    rf'\b{_NUM}\+?\s+(?:{_ENTITY})\b',                                         # 500 customers
    rf'\b{_NUM}\+?\s+(?:years?|vuotta|vuoden)\b',                              # 10 years
    rf'\b{_NUM}(?:\s?/\s?5|\s+out of 5|\s+stars?)\b',                          # 4.8/5
    r'\b(?:since|founded in|established in|vuodesta)\s+(?:19|20)\d{2}\b',      # since 2015
]
_CLAIM_RE = re.compile('|'.join(f'(?:{p})' for p in CLAIM_PATTERNS), re.I)
_NUMBER_RE = re.compile(_NUM)

ATTRIBUTION_RE = re.compile(
    r'\b(?:according to|studies (?:show|suggest|find|found)|a (?:recent )?(?:study|survey|report|poll)'
    r'(?: by| from| of)?|research (?:shows|suggests|finds|found|from|by)|experts? (?:say|agree|recommend)'
    r'|data (?:from|shows)|statistics show|tutkimuksen mukaan|tutkimukset osoittavat)\b', re.I)
QUOTE_RE = re.compile(r'["“”„]([^"“”„]{15,})["“”„]')


def _norm(n: str) -> str:
    n = n.replace(' ', '')
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+', n):    # 1,500 -> 1500
        n = n.replace(',', '')
    n = n.replace(',', '.')
    return n.rstrip('.').lstrip('0') or '0'


def source_numbers(sources: str) -> set[str]:
    return {_norm(m) for m in _NUMBER_RE.findall(sources or '')}


def _supported(claim: str, known: set[str]) -> bool:
    nums = [_norm(m) for m in _NUMBER_RE.findall(claim)]
    return bool(nums) and all(n in known for n in nums)


def _clean_text(text: str, known: set[str], removed: list) -> str:
    if not text or not isinstance(text, str):
        return text

    def repl(m):
        claim = m.group(0)
        if _supported(claim, known):
            return claim
        start = max(0, m.start() - 50)
        removed.append({'claim': claim.strip(), 'context': text[start:m.end() + 50].strip()})
        return PLACEHOLDER

    return _CLAIM_RE.sub(repl, text)


def _fields(piece):
    yield 'title', piece.title
    yield 'headline', piece.headline
    for i, s in enumerate(piece.sections or []):
        yield ('section', i, 'heading'), s.get('heading', '')
        yield ('section', i, 'body'), s.get('body', '')
    yield 'cta', piece.cta
    yield 'seo_title', getattr(piece, 'seo_title', '')
    yield 'seo_description', getattr(piece, 'seo_description', '')


def check_and_clean(piece, sources: str):
    """Return (cleaned piece, report). The piece is copied, not changed in place."""
    known = source_numbers(sources)
    low_sources = (sources or '').lower()
    piece = piece.model_copy(deep=True)
    removed, flagged = [], []
    for key, value in list(_fields(piece)):
        cleaned = _clean_text(value, known, removed)
        if isinstance(key, tuple):
            piece.sections[key[1]][key[2]] = cleaned
        else:
            setattr(piece, key, cleaned)
        if not isinstance(cleaned, str):
            continue
        for m in ATTRIBUTION_RE.finditer(cleaned):
            flagged.append({'type': 'source', 'text': cleaned[max(0, m.start() - 30):m.end() + 70].strip()})
        for m in QUOTE_RE.finditer(cleaned):
            if m.group(1).strip().lower() not in low_sources:
                flagged.append({'type': 'quote', 'text': m.group(0)[:160]})
    text = ' '.join(v for _, v in _fields(piece) if isinstance(v, str))
    return piece, {
        'removed': removed,
        'flagged': flagged,
        'placeholders': text.count(PLACEHOLDER),
    }


def merge_reports(*reports) -> dict:
    out = {'removed': [], 'flagged': [], 'placeholders': 0}
    for r in reports:
        if not r:
            continue
        out['removed'] += r.get('removed', [])
        out['flagged'] += r.get('flagged', [])
        out['placeholders'] += r.get('placeholders', 0)
    return out
