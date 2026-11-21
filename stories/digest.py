"""Daily AI & ML digest for Stories.

Every morning (after NEWS_DIGEST_HOUR, Helsinki time) collect the day's top
items from public feeds — Hugging Face Daily Papers, AI lab and research
blogs, AI stories on Hacker News — write a short summary of each in our own
words, and publish one "AI & ML Digest" story with a citation and link for
every item, so readers go to the source for the full text.

Rules that keep it honest and legal:
- Summaries use only the item's own abstract/description (no full articles
  copied), are 2-3 sentences, and any sentence with a number that is not in
  the source text is dropped.
- Every item links to and names its source; nothing is shown without one.
- An item used on one day is never repeated (DigestItem.url is unique).
"""
import email.utils
import html
import json
import logging
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)

HELSINKI = ZoneInfo('Europe/Helsinki')
UA = 'Mozilla/5.0 (compatible; HasanAI-digest/1.0; +https://hasanai.net/stories/)'
FEEDS = [
    # (publisher, url, needs an AI keyword match)
    ('OpenAI', 'https://openai.com/news/rss.xml', False),
    ('Google DeepMind', 'https://deepmind.google/blog/rss.xml', False),
    ('Google Research', 'https://research.google/blog/rss/', False),
    ('Hugging Face', 'https://huggingface.co/blog/feed.xml', False),
    ('NVIDIA', 'https://blogs.nvidia.com/feed/', True),
    ('Berkeley AI Research', 'https://bair.berkeley.edu/blog/feed.xml', False),
    ('MIT News', 'https://news.mit.edu/rss/topic/artificial-intelligence2', False),
    ('MIT Technology Review', 'https://www.technologyreview.com/topic/artificial-intelligence/feed', False),
]
AI_WORDS = re.compile(
    r'\b(ai|a\.i\.|artificial intelligence|machine learning|ml|deep learning|neural|llm|llms|language model|'
    r'gpt|transformer|diffusion|agent|agents|reinforcement learning|computer vision|dataset|benchmark|'
    r'model|models|inference|training|gpu|robot|robotics)\b', re.I)
MAX_PAPERS, MAX_NEWS, MAX_HN = 3, 4, 2
NEWS_WINDOW = timedelta(hours=36)
HN_MIN_SCORE = 100
_NUM = re.compile(r'\d+(?:[.,]\d+)*')


# ── fetching ─────────────────────────────────────────────────────────────────

def _get(url: str, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2_000_000)


def _text(fragment: str, limit=1500) -> str:
    """Plain text from an HTML fragment (feed descriptions)."""
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', fragment or '', flags=re.S | re.I)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
    return re.sub(r'\s+', ' ', t).strip()[:limit]


def _date(value: str):
    if not value:
        return None
    value = value.strip()
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt_timezone.utc)


def parse_feed(data: bytes) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, url, text, date}]."""
    root = ET.fromstring(data)
    out = []
    for item in root.iter():
        tag = item.tag.split('}')[-1]
        if tag not in ('item', 'entry'):
            continue
        fields = {c.tag.split('}')[-1]: c for c in item}
        title = _text(fields['title'].text if 'title' in fields else '', 300)
        link = ''
        if 'link' in fields:
            link = (fields['link'].text or '').strip() or fields['link'].get('href', '')
        for c in item:   # Atom: <link rel="alternate" href=...>
            if c.tag.split('}')[-1] == 'link' and c.get('href') and c.get('rel', 'alternate') == 'alternate':
                link = c.get('href')
                break
        body = ''
        for key in ('description', 'summary', 'content', 'encoded'):
            if key in fields and (fields[key].text or '').strip():
                body = fields[key].text
                break
        when = None
        for key in ('pubDate', 'published', 'updated', 'date'):
            if key in fields:
                when = _date(fields[key].text or '')
                if when:
                    break
        if title and link.startswith('http'):
            out.append({'title': title, 'url': link.strip(), 'text': _text(body), 'date': when})
    return out


def _meta_description(url: str) -> str:
    """og:description / meta description of a linked article (Hacker News items)."""
    try:
        page = _get(url, timeout=10).decode('utf-8', 'replace')
    except Exception:
        return ''
    for pat in (r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description'):
        m = re.search(pat, page, re.I)
        if m:
            return _text(m.group(1), 800)
    return ''


def collect(now=None, log=print) -> dict:
    """Candidate items per section, best first."""
    now = now or timezone.now()
    papers, news, hn = [], [], []
    try:
        for p in json.loads(_get('https://huggingface.co/api/daily_papers')):
            paper = p.get('paper') or {}
            pid = paper.get('id') or ''
            if not pid or not (paper.get('summary') or p.get('summary')):
                continue
            papers.append({
                'section': 'papers', 'title': _text(paper.get('title') or p.get('title'), 300),
                'url': f'https://arxiv.org/abs/{pid}', 'source': 'arXiv (via Hugging Face Daily Papers)',
                'text': _text(paper.get('summary') or p.get('summary'), 2000),
                'date': _date(paper.get('publishedAt') or p.get('publishedAt') or ''),
                'score': int(paper.get('upvotes') or 0),
            })
    except Exception as exc:
        log(f'  papers: {exc}')
    papers.sort(key=lambda i: -i['score'])

    for publisher, url, needs_ai in FEEDS:
        try:
            for it in parse_feed(_get(url)):
                if not it['date'] or now - it['date'] > NEWS_WINDOW or it['date'] > now + timedelta(hours=2):
                    continue
                if needs_ai and not AI_WORDS.search(it['title'] + ' ' + it['text']):
                    continue
                if len(it['text']) < 80:
                    continue
                news.append({**it, 'section': 'news', 'source': publisher, 'score': it['date'].timestamp()})
        except Exception as exc:
            log(f'  {publisher}: {exc}')
    news.sort(key=lambda i: -i['score'])

    try:
        for sid in json.loads(_get('https://hacker-news.firebaseio.com/v0/topstories.json'))[:60]:
            item = json.loads(_get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=10))
            if not item or item.get('score', 0) < HN_MIN_SCORE or not item.get('url'):
                continue
            if not AI_WORDS.search(item.get('title', '')):
                continue
            hn.append({'section': 'hn', 'title': _text(item['title'], 300), 'url': item['url'],
                       'source': 'Hacker News discussion', 'discussion': f'https://news.ycombinator.com/item?id={sid}',
                       'text': '', 'date': datetime.fromtimestamp(item.get('time', 0), dt_timezone.utc),
                       'score': item['score']})
    except Exception as exc:
        log(f'  hacker news: {exc}')
    hn.sort(key=lambda i: -i['score'])
    return {'papers': papers, 'news': news, 'hn': hn}


def select(candidates: dict, used_urls: set) -> list[dict]:
    """Pick the day's items, never reusing a URL and at most 2 news items per publisher."""
    picked, per_source = [], {}
    for section, limit in (('papers', MAX_PAPERS), ('news', MAX_NEWS), ('hn', MAX_HN)):
        n = 0
        for it in candidates.get(section, []):
            if n >= limit:
                break
            if it['url'] in used_urls:
                continue
            if section != 'papers' and per_source.get(it['source'], 0) >= 2:   # variety in the news
                continue
            if section == 'hn':
                it['text'] = _meta_description(it['url'])
                if len(it['text']) < 60:
                    continue
            used_urls.add(it['url'])
            per_source[it['source']] = per_source.get(it['source'], 0) + 1
            picked.append(it)
            n += 1
    return picked


# ── summarising ──────────────────────────────────────────────────────────────

def _numbers(text: str) -> set:
    return {n.replace(',', '.').rstrip('.').lstrip('0') or '0' for n in _NUM.findall(text or '')}


def _grounded(text: str, source: str) -> str:
    """Drop sentences containing numbers that are not in the source text."""
    known = _numbers(source)
    keep = [s for s in re.split(r'(?<=[.!?])\s+', (text or '').strip()) if s and _numbers(s) <= known]
    return ' '.join(keep)


def summarize(items: list[dict], log=print) -> list[dict]:
    from content_generator.pipeline.agents.gemini_client import generate
    done = []
    for start in range(0, len(items), 4):
        batch = items[start:start + 4]
        listing = '\n\n'.join(
            f'[{i}] TITLE: {it["title"]}\nSOURCE: {it["source"]}\nTEXT: {it["text"][:1500]}'
            for i, it in enumerate(batch))
        prompt = f"""You write a daily AI & machine-learning news digest for engineers.

For each item below write:
- "summary": 2-3 sentences, in your own words, saying what it is and what is new
- "why": 1 sentence on why it matters to an ML practitioner

Rules:
- Use ONLY the item's TEXT. Do not add facts, names, numbers or claims that are not in it.
- Do not copy phrases of more than 8 words from the TEXT; rephrase.
- Neutral tone, no hype words ("revolutionary", "game-changing").
- If the TEXT is too thin to say anything real, return an empty summary for that item.

ITEMS:
{listing}

Return JSON: {{"items": [{{"n": <index>, "summary": str, "why": str}}, ...]}}
Return ONLY the JSON."""
        try:
            data = json.loads(generate(prompt))
        except Exception as exc:
            log(f'  summary batch failed: {exc}')
            continue
        rows = data.get('items', data) if isinstance(data, dict) else data
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                it = batch[int(row.get('n'))]
            except (TypeError, ValueError, IndexError):
                continue
            summary = _grounded(row.get('summary', ''), it['text'] + ' ' + it['title'])
            why = _grounded(row.get('why', ''), it['text'] + ' ' + it['title'])
            if len(summary) >= 40:
                done.append({**it, 'summary': summary, 'why': why})
    return done


# ── publishing ───────────────────────────────────────────────────────────────

SECTION_TITLES = {'papers': 'Research papers', 'news': 'From the labs and newsrooms', 'hn': 'Discussed on Hacker News'}


def render_html(items: list[dict], day) -> str:
    e = html.escape
    parts = [f'<p>The day\'s notable AI and machine-learning papers and news, summarised. '
             f'Each item links to its source; read the original for the full details.</p>']
    for section in ('papers', 'news', 'hn'):
        rows = [i for i in items if i['section'] == section]
        if not rows:
            continue
        parts.append(f'<h2>{SECTION_TITLES[section]}</h2>')
        for it in rows:
            when = it['date'].astimezone(HELSINKI).strftime('%d %b %Y') if it.get('date') else ''
            parts.append(f'<h3><a href="{e(it["url"])}" target="_blank">{e(it["title"])}</a></h3>')
            parts.append(f'<p>{e(it["summary"])}</p>')
            if it.get('why'):
                parts.append(f'<p><strong>Why it matters:</strong> {e(it["why"])}</p>')
            cite = f'Source: <a href="{e(it["url"])}" target="_blank">{e(it["source"])}</a>'
            if it.get('discussion'):
                cite += f' · <a href="{e(it["discussion"])}" target="_blank">discussion</a>'
            if when:
                cite += f' · {when}'
            parts.append(f'<p><em>{cite}</em></p>')
    parts.append('<hr><p><em>Summaries are generated automatically from each source\'s own abstract or '
                 'description and may simplify. Always check the original before relying on a detail.</em></p>')
    return '\n'.join(parts)


def publish(items: list[dict], day):
    from django.contrib.auth import get_user_model
    from .models import DigestItem, Story, Tag
    import os
    User = get_user_model()
    author = (User.objects.filter(username=os.environ.get('SUPERUSER_USERNAME', 'seyed')).first()
              or User.objects.filter(is_superuser=True).order_by('pk').first())
    title = f'AI & ML Digest — {day.strftime("%d %b %Y")}'
    lead = '; '.join(i['title'] for i in items[:3])
    story, _ = Story.objects.update_or_create(
        slug=f'ai-ml-digest-{day.isoformat()}',
        defaults=dict(author=author, title=title, excerpt=f'Today: {lead}'[:290],
                      content=render_html(items, day), status=Story.Status.PUBLISHED,
                      published_at=timezone.now()))
    for name in ('AI News', 'Digest'):
        tag, _ = Tag.objects.get_or_create(name=name, defaults={'slug': slugify(name)})
        story.tags.add(tag)
    for it in items:
        DigestItem.objects.get_or_create(url=it['url'][:500], defaults={
            'title': it['title'][:300], 'source': it['source'][:100], 'digest_date': day})
    return story


def make_digest(day=None, dry_run=False, log=print):
    """Collect, pick, summarise and publish. Returns (story or None, items)."""
    from .models import DigestItem
    day = day or timezone.now().astimezone(HELSINKI).date()
    used = set(DigestItem.objects.values_list('url', flat=True))
    candidates = collect(log=log)
    log(f'candidates: {len(candidates["papers"])} papers, {len(candidates["news"])} news, {len(candidates["hn"])} HN')
    picked = select(candidates, used)
    log(f'picked {len(picked)}: ' + '; '.join(f'[{i["section"]}] {i["title"][:60]}' for i in picked))
    if dry_run or not picked:
        return None, picked
    items = summarize(picked, log=log)
    log(f'summarised {len(items)} item(s)')
    if not items:
        return None, items
    return publish(items, day), items


# ── schedule ─────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_last_check = 0.0


def is_due(now=None) -> bool:
    from .models import DailyDigest
    if not getattr(settings, 'NEWS_DIGEST_ENABLED', True):
        return False
    local = (now or timezone.now()).astimezone(HELSINKI)
    if local.hour < getattr(settings, 'NEWS_DIGEST_HOUR', 7):
        return False
    rec = DailyDigest.objects.filter(date=local.date()).first()
    if rec is None:
        return True
    if rec.status in ('done', 'empty'):
        return False
    if rec.status == 'running':
        return timezone.now() - rec.updated_at > timedelta(minutes=30)
    return rec.attempts < 3 and timezone.now() - rec.updated_at > timedelta(hours=1)


def run_today(log=None):
    from .models import DailyDigest
    day = timezone.now().astimezone(HELSINKI).date()
    rec, _ = DailyDigest.objects.get_or_create(date=day)
    rec.status, rec.attempts = 'running', rec.attempts + 1
    rec.save(update_fields=['status', 'attempts', 'updated_at'])
    lines = []

    def say(msg):
        lines.append(str(msg))
        if log:
            log(msg)

    try:
        story, items = make_digest(day, log=say)
        rec.story = story
        rec.items = len(items) if story else 0
        rec.status = 'done' if story else 'empty'
    except Exception as exc:
        logger.exception('Daily digest failed')
        say(f'failed: {type(exc).__name__}: {exc}')
        rec.status = 'failed'
    rec.log = '\n'.join(lines)[-10000:]
    rec.save()
    return rec


def maybe_run() -> bool:
    """Called by the idle worker; checks at most every 10 minutes."""
    global _last_check
    if time.monotonic() - _last_check < 600:
        return False
    _last_check = time.monotonic()
    if not _lock.acquire(blocking=False):
        return False
    try:
        due = is_due()
    except Exception:
        _lock.release()
        raise
    if not due:
        _lock.release()
        return False

    def work():
        try:
            run_today()
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='daily-digest', daemon=True).start()
    return True
