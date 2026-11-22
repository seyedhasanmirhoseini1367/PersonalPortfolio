"""Daily AI & ML digest (and the Monday weekly roundup) for Stories.

Every morning (after NEWS_DIGEST_HOUR, Helsinki time) collect the day's top
items from the news sources managed in the admin (NewsSource) — Hugging Face
Daily Papers, AI lab and research blogs, AI stories on Hacker News — write a
short summary of each in our own words, and publish one "AI & ML Digest"
story with a citation and link for every item, so readers go to the source
for the full text. Each Monday, the past week's items are boiled down to a
"top 5 of the week" roundup.

Rules that keep it honest and legal:
- Summaries use only the item's own abstract/description (no full articles
  copied), are 2-3 sentences, and any sentence with a number that is not in
  the source text is dropped.
- Every item links to and names its source; nothing is shown without one.
- An item used on one day is never repeated (DigestItem.url is unique), and
  a story already covered this week is not covered again under another URL.
- No finance / stock-market news; the same story from several outlets is
  shown once, with "also covered by" links.
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
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)

HELSINKI = ZoneInfo('Europe/Helsinki')
UA = 'Mozilla/5.0 (compatible; HasanAI-digest/1.0; +https://hasanai.net/stories/)'
HF_PAPERS_URL = 'https://huggingface.co/api/daily_papers'
HN_TOP_URL = 'https://hacker-news.firebaseio.com/v0/topstories.json'
AI_WORDS = re.compile(
    r'\b(ai|a\.i\.|artificial intelligence|machine learning|ml|deep learning|neural|llm|llms|language model|'
    r'gpt|transformer|diffusion|agent|agents|reinforcement learning|computer vision|dataset|benchmark|'
    r'model|models|inference|training|gpu|robot|robotics)\b', re.I)
# Markets, not machine learning: dropped from news and Hacker News.
FINANCE = re.compile(
    r'\b(stocks?|stock market|share prices?|shares (?:fell|rose|jumped|dropped|slid|soared|tumbled|surged)|'
    r'shareholders?|nasdaq|nyse|dow jones|s&p 500|wall street|sell-?off|ipo|earnings|quarterly results|'
    r'investors?|valuation|market cap(?:italization)?|funding round|series [a-f] round|hedge funds?|'
    r'crypto(?:currency)?|bitcoin|trading)\b', re.I)
TOPICS = ['LLMs', 'Computer Vision', 'Robotics', 'Audio & Speech', 'ML Research',
          'Tools & Open Source', 'Industry', 'Safety & Policy', 'Science & Health']
_TOPIC_GUESS = [
    ('Safety & Policy', r'\b(safety|alignment|policy|regulation|law|copyright|privacy|misuse|governance)\b'),
    ('Robotics', r'\b(robot|robots|robotics|humanoid|embodied|autonomous driving|self-driving)\b'),
    ('Audio & Speech', r'\b(speech|audio|voice|music|asr|text-to-speech|tts)\b'),
    ('Computer Vision', r'\b(image|images|video|vision|visual|3d|segmentation|detection|diffusion)\b'),
    ('Science & Health', r'\b(protein|biology|medical|medicine|health|clinical|chemistry|climate|weather|physics)\b'),
    ('Tools & Open Source', r'\b(open[- ]source|library|framework|sdk|api|release|github|toolkit)\b'),
    ('LLMs', r'\b(llm|llms|language model|chatbot|gpt|reasoning|token|tokens|prompt|agents?)\b'),
]
MAX_PAPERS, MAX_NEWS, MAX_HN, WEEKLY_TOP = 3, 4, 2, 5
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


def is_finance(item: dict) -> bool:
    return bool(FINANCE.search(item.get('title', '') + ' ' + item.get('text', '')))


def _sources():
    from .models import NewsSource
    return list(NewsSource.objects.filter(active=True))


def collect(now=None, log=print) -> dict:
    """Candidate items per section from the active NewsSources, best first."""
    from .models import NewsSource
    now = now or timezone.now()
    papers, news, hn = [], [], []
    for src in _sources():
        try:
            if src.kind == NewsSource.KIND_HF:
                for p in json.loads(_get(src.url or HF_PAPERS_URL)):
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
            elif src.kind == NewsSource.KIND_HN:
                for sid in json.loads(_get(src.url or HN_TOP_URL))[:60]:
                    item = json.loads(_get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=10))
                    if not item or item.get('score', 0) < HN_MIN_SCORE or not item.get('url'):
                        continue
                    if not AI_WORDS.search(item.get('title', '')):   # HN covers everything: always AI-only
                        continue
                    hn.append({'section': 'hn', 'title': _text(item['title'], 300), 'url': item['url'],
                               'source': 'Hacker News discussion',
                               'discussion': f'https://news.ycombinator.com/item?id={sid}',
                               'text': '', 'date': datetime.fromtimestamp(item.get('time', 0), dt_timezone.utc),
                               'score': item['score']})
            elif src.url:
                for it in parse_feed(_get(src.url)):
                    if not it['date'] or now - it['date'] > NEWS_WINDOW or it['date'] > now + timedelta(hours=2):
                        continue
                    if src.ai_filter and not AI_WORDS.search(it['title'] + ' ' + it['text']):
                        continue
                    if len(it['text']) < 80:
                        continue
                    news.append({**it, 'section': 'news', 'source': src.name, 'score': it['date'].timestamp()})
        except Exception as exc:
            log(f'  {src.name}: {exc}')
    papers.sort(key=lambda i: -i['score'])
    news.sort(key=lambda i: -i['score'])
    hn.sort(key=lambda i: -i['score'])
    news = [i for i in news if not is_finance(i)]
    hn = [i for i in hn if not is_finance(i)]
    return {'papers': papers, 'news': news, 'hn': hn}


# ── duplicates ───────────────────────────────────────────────────────────────

_STOP = {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'new', 'its', 'are', 'how', 'why', 'what',
         'into', 'about', 'now', 'can', 'will', 'has', 'have', 'was', 'our', 'your', 'you', 'out', 'more',
         'than', 'over', 'after', 'says', 'introducing', 'announces', 'launches', 'just'}


def _tokens(title: str) -> set:
    return {w for w in re.findall(r'[a-z0-9]+', (title or '').lower()) if len(w) > 2 and w not in _STOP}


def same_story(a: str, b: str) -> bool:
    """Two headlines about the same thing (most words of the shorter one shared)."""
    ta, tb = _tokens(a), _tokens(b)
    shared = len(ta & tb)
    return shared >= 3 and shared / min(len(ta), len(tb)) >= 0.6


def merge_duplicates(candidates: dict) -> dict:
    """The same story from several outlets (news and HN) is kept once, best first,
    with the others listed under 'also'."""
    kept = []
    for it in candidates.get('news', []) + candidates.get('hn', []):
        twin = next((k for k in kept if same_story(k['title'], it['title'])), None)
        if twin is None:
            kept.append({**it, 'also': list(it.get('also', []))})
        elif it['source'] != twin['source'] and len(twin['also']) < 3:
            twin['also'].append({'source': it['source'].replace(' discussion', ''), 'url': it['url']})
    return {**candidates, 'news': [i for i in kept if i['section'] == 'news'],
            'hn': [i for i in kept if i['section'] == 'hn']}


def select(candidates: dict, used_urls: set, recent_titles=()) -> list[dict]:
    """Pick the day's items: never reusing a URL or a story covered in the last days,
    at most 2 news items per publisher."""
    picked, per_source = [], {}
    recent = list(recent_titles)
    for section, limit in (('papers', MAX_PAPERS), ('news', MAX_NEWS), ('hn', MAX_HN)):
        n = 0
        for it in candidates.get(section, []):
            if n >= limit:
                break
            if it['url'] in used_urls:
                continue
            if section != 'papers' and per_source.get(it['source'], 0) >= 2:   # variety in the news
                continue
            if section != 'papers' and any(same_story(it['title'], t) for t in recent):
                continue
            if section == 'hn':
                it['text'] = _meta_description(it['url'])
                if len(it['text']) < 60:
                    continue
            used_urls.add(it['url'])
            recent.append(it['title'])
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


def guess_topic(item: dict) -> str:
    text = f"{item.get('title', '')} {item.get('text', '')}"
    for topic, pat in _TOPIC_GUESS:
        if re.search(pat, text, re.I):
            return topic
    return 'ML Research' if item.get('section') == 'papers' else 'Industry'


def _topic(value, item) -> str:
    value = (value or '').strip().lower()
    for t in TOPICS:
        if t.lower() == value:
            return t
    return guess_topic(item)


def summarize(items: list[dict], log=print) -> list[dict]:
    from content_generator.pipeline.agents.gemini_client import generate
    done = []
    topics = ', '.join(f'"{t}"' for t in TOPICS)
    for start in range(0, len(items), 4):
        batch = items[start:start + 4]
        listing = '\n\n'.join(
            f'[{i}] TITLE: {it["title"]}\nSOURCE: {it["source"]}\nTEXT: {it["text"][:1500]}'
            for i, it in enumerate(batch))
        prompt = f"""You write a daily AI & machine-learning news digest for engineers.

For each item below write:
- "summary": 2-3 sentences, in your own words, saying what it is and what is new
- "why": 1 sentence on why it matters to an ML practitioner
- "topic": exactly one of {topics}

Rules:
- Use ONLY the item's TEXT. Do not add facts, names, numbers or claims that are not in it.
- Do not copy phrases of more than 8 words from the TEXT; rephrase.
- Neutral tone, no hype words ("revolutionary", "game-changing").
- If the TEXT is too thin to say anything real, return an empty summary for that item.

ITEMS:
{listing}

Return JSON: {{"items": [{{"n": <index>, "summary": str, "why": str, "topic": str}}, ...]}}
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
                done.append({**it, 'summary': summary, 'why': why, 'topic': _topic(row.get('topic'), it)})
    return done


# ── "learn the basics" links to ML Explained walkthroughs ────────────────────

# Extra phrases (regex) that point a news item at a walkthrough; titles are matched too.
LEARN_ALIASES = {
    'rag-retrieval-augmented-generation': [r'retrieval[- ]augmented', r'\bRAG\b'],
    'diffusion-models-ddpm-and-stable-diffusion': [r'diffusion models?', r'stable diffusion', r'text-to-image',
                                                   r'image generation', r'video generation'],
    'rlhf-grpo-constitutional-ai': [r'\bRLHF\b', r'\bGRPO\b', r'human feedback', r'\bDPO\b',
                                    r'preference optimi[sz]ation'],
    'reinforcement-learning': [r'reinforcement learning'],
    'peft-parameter-efficient-fine-tuning': [r'fine-?tun(?:e|ed|es|ing)'],
    'attention-is-all-you-need': [r'\btransformers?\b', r'self-attention', r'attention mechanism'],
    'tokenization-byte-pair-encoding': [r'tokeni[sz](?:er|ers|ation)'],
    'positional-embeddings-from-sinusoids-to-rope': [r'\bRoPE\b', r'positional (?:embedding|encoding)s?',
                                                     r'long[- ]context'],
    'vit-an-image-is-worth-16x16-words': [r'vision transformers?'],
    'convolutional-networks': [r'\bCNNs?\b', r'convolutional'],
    'gans-generative-adversarial-networks': [r'adversarial networks?'],
    'vae-auto-encoding-variational-bayes': [r'variational auto-?encoders?'],
    'autoencoders': [r'\bauto-?encoders?\b'],
    'self-improving-llms': [r'self-improv\w*', r'self-play'],
    'gpt-generative-pre-training': [r'large language models?'],
    'optimisers-sgd-to-adam': [r'optimi[sz]ers?', r'\bMuon\b'],
    'kimi-k3-delta-attention-attention-residuals-latentmoe': [r'mixture[- ]of[- ]experts', r'\bMoE\b'],
    'deepseek-v4-compressed-sparse-attention-and-muon': [r'sparse attention'],
    'rnn-lstm': [r'\bLSTMs?\b', r'recurrent neural'],
    'feature-importance-shap': [r'\bSHAP\b', r'interpretability', r'explainability'],
    'data-leakage': [r'data leakage', r'contamination'],
    'probability-calibration': [r'calibration'],
    'evaluation-metrics': [r'evaluation metrics?'],
}
_SKIP_TITLES = {'how-models-learn-the-concepts', 'exploratory-data-analysis'}


def _walkthrough_patterns():
    """[(slug, title, url, [compiled patterns])] for published walkthroughs."""
    try:
        from model_internals.models import Walkthrough
        rows = list(Walkthrough.objects.filter(is_published=True).values_list('slug', 'title'))
    except Exception:
        return []
    out = []
    for slug, title in rows:
        if slug in _SKIP_TITLES:
            continue
        # Acronyms (RAG, LoRA, ViT) are matched case-sensitively, phrases are not.
        pats = [re.compile(p, 0 if re.search(r'[A-Z]{2}', p) else re.I) for p in LEARN_ALIASES.get(slug, [])]
        for name in re.split(r'[&,]', title.split(':')[0]):
            name = name.strip()
            if len(name) >= 3:
                exact = bool(re.search(r'[A-Z].*[A-Z]', name)) and ' ' not in name
                pats.append(re.compile(r'(?<![\w-])' + re.escape(name) + r'(?!\w)', 0 if exact else re.I))
        out.append((slug, title, reverse('model_internals:walkthrough_detail', args=[slug]), pats))
    return out


def learn_links(item: dict, patterns, limit=2) -> list[dict]:
    """Walkthroughs whose name or key phrase appears in the item (title hits first)."""
    hits = []
    for slug, title, url, pats in patterns:
        if any(p.search(item.get('title', '')) for p in pats):
            hits.append((0, title, url))
        elif any(p.search(item.get('summary', '') + ' ' + item.get('text', '')) for p in pats):
            hits.append((1, title, url))
    hits.sort(key=lambda h: h[0])
    return [{'title': t, 'url': u} for _, t, u in hits[:limit]]


# ── publishing ───────────────────────────────────────────────────────────────

SECTION_TITLES = {'papers': 'Research papers', 'news': 'From the labs and newsrooms', 'hn': 'Discussed on Hacker News'}
WEEKLY_TOP_TITLE = 'Top stories of the week'
DISCLAIMER = ('<hr><p><em>Summaries are generated automatically from each source\'s own abstract or '
              'description and may simplify. Always check the original before relying on a detail.</em></p>')


def _topic_url(topic: str) -> str:
    return reverse('stories:tag_stories', args=[slugify(topic)])


def render_item(it: dict, show_day=False) -> list[str]:
    e = html.escape
    parts = [f'<h3><a href="{e(it["url"])}" target="_blank">{e(it["title"])}</a></h3>']
    if it.get('topic'):
        parts.append(f'<p class="digest-meta"><a class="digest-topic" href="{_topic_url(it["topic"])}">'
                     f'{e(it["topic"])}</a></p>')
    parts.append(f'<p>{e(it["summary"])}</p>')
    if it.get('why'):
        parts.append(f'<p><strong>Why it matters:</strong> {e(it["why"])}</p>')
    if it.get('learn'):
        links = ' · '.join(f'<a href="{e(l["url"])}">{e(l["title"])}</a>' for l in it['learn'])
        parts.append(f'<p class="digest-learn"><strong>Learn the basics:</strong> {links}</p>')
    cite = f'Source: <a href="{e(it["url"])}" target="_blank">{e(it["source"])}</a>'
    if it.get('discussion'):
        cite += f' · <a href="{e(it["discussion"])}" target="_blank">discussion</a>'
    if it.get('also'):
        cite += ' · also covered by ' + ', '.join(
            f'<a href="{e(a["url"])}" target="_blank">{e(a["source"])}</a>' for a in it['also'])
    when = it.get('date')
    if when:
        cite += f' · {when.astimezone(HELSINKI).strftime("%d %b %Y")}'
    elif show_day and it.get('day'):
        cite += f' · {it["day"].strftime("%d %b %Y")}'
    parts.append(f'<p><em>{cite}</em></p>')
    return parts


def render_html(items: list[dict], day) -> str:
    parts = ['<p>The day\'s notable AI and machine-learning papers and news, summarised. '
             'Each item links to its source; read the original for the full details.</p>']
    for section in ('papers', 'news', 'hn'):
        rows = [i for i in items if i['section'] == section]
        if not rows:
            continue
        parts.append(f'<h2>{SECTION_TITLES[section]}</h2>')
        for it in rows:
            parts += render_item(it)
    parts.append(DISCLAIMER)
    return '\n'.join(parts)


def _author():
    from django.contrib.auth import get_user_model
    import os
    User = get_user_model()
    return (User.objects.filter(username=os.environ.get('SUPERUSER_USERNAME', 'seyed')).first()
            or User.objects.filter(is_superuser=True).order_by('pk').first())


def _tag(story, names):
    from .models import Tag
    for name in names:
        tag = Tag.objects.filter(name=name).first() or Tag.objects.create(name=name, slug=slugify(name))
        story.tags.add(tag)


def publish(items: list[dict], day):
    from .models import DigestItem, Story
    patterns = _walkthrough_patterns()
    for it in items:
        it['learn'] = learn_links(it, patterns)
    title = f'AI & ML Digest — {day.strftime("%d %b %Y")}'
    counts = {k: sum(1 for i in items if i['section'] == k) for k in ('papers', 'news', 'hn')}
    lead = (f"{counts['papers']} papers, {counts['news']} news items and {counts['hn']} discussions. "
            f"Top: {items[0]['title']}")
    story, _ = Story.objects.update_or_create(
        slug=f'ai-ml-digest-{day.isoformat()}',
        defaults=dict(author=_author(), title=title, excerpt=lead[:290],
                      content=render_html(items, day), status=Story.Status.PUBLISHED,
                      published_at=timezone.now()))
    _tag(story, ['AI News', 'Digest'] + sorted({i['topic'] for i in items if i.get('topic')}))
    for rank, it in enumerate(items):
        DigestItem.objects.update_or_create(url=it['url'][:500], defaults={
            'title': it['title'][:300], 'source': it['source'][:100], 'digest_date': day,
            'section': it['section'], 'topic': it.get('topic', ''), 'summary': it['summary'],
            'why': it.get('why', ''), 'also': it.get('also', []),
            # rank within its section on the day: lower is better, used by the weekly fallback
            'score': float(sum(1 for j in items[:rank] if j['section'] == it['section']))})
    return story


def make_digest(day=None, dry_run=False, log=print):
    """Collect, pick, summarise and publish. Returns (story or None, items)."""
    from .models import DigestItem
    day = day or timezone.now().astimezone(HELSINKI).date()
    used = set(DigestItem.objects.values_list('url', flat=True))
    recent = list(DigestItem.objects.filter(digest_date__gte=day - timedelta(days=4))
                  .values_list('title', flat=True))
    candidates = merge_duplicates(collect(log=log))
    log(f'candidates: {len(candidates["papers"])} papers, {len(candidates["news"])} news, {len(candidates["hn"])} HN')
    picked = select(candidates, used, recent)
    log(f'picked {len(picked)}: ' + '; '.join(f'[{i["section"]}] {i["title"][:60]}' for i in picked))
    if dry_run or not picked:
        return None, picked
    items = summarize(picked, log=log)
    log(f'summarised {len(items)} item(s)')
    if not items:
        return None, items
    return publish(items, day), items


# ── weekly roundup ───────────────────────────────────────────────────────────

def _week_items(week_start):
    from .models import DigestItem
    rows = DigestItem.objects.filter(digest_date__gte=week_start, digest_date__lt=week_start + timedelta(days=7)
                                     ).exclude(summary='').order_by('digest_date', 'score', 'pk')
    return [{'title': r.title, 'url': r.url, 'source': r.source, 'section': r.section or 'news',
             'topic': r.topic, 'summary': r.summary, 'why': r.why, 'also': r.also or [],
             'day': r.digest_date, 'rank': r.score} for r in rows]


def _fallback_top(items, k=WEEKLY_TOP):
    """Without the model: the best-ranked item of each day, alternating sections."""
    order = sorted(items, key=lambda i: (i['rank'], {'news': 0, 'papers': 1, 'hn': 2}.get(i['section'], 3),
                                         -i['day'].toordinal()))
    return order[:k]


def pick_weekly(items, log=print, k=WEEKLY_TOP):
    """The k most important items of the week (one model call; falls back to ranks)."""
    if len(items) <= k:
        return items
    listing = '\n'.join(f'[{n}] ({i["section"]}, {i["topic"] or "-"}) {i["title"]} — {i["summary"][:220]}'
                        for n, i in enumerate(items))
    prompt = f"""Below are this week's AI & machine-learning news items.
Pick the {k} that matter most to ML engineers: real advances, important releases, widely-used tools,
significant research. Prefer variety of topics; avoid near-duplicates.

{listing}

Return JSON: {{"top": [<index>, ...]}} with exactly {k} indices, most important first. Return ONLY the JSON."""
    try:
        from content_generator.pipeline.agents.gemini_client import generate
        data = json.loads(generate(prompt))
        idx = [int(n) for n in (data.get('top') if isinstance(data, dict) else data)]
        top = []
        for n in idx:
            if 0 <= n < len(items) and items[n] not in top:
                top.append(items[n])
        if len(top) >= 3:
            return top[:k]
    except Exception as exc:
        log(f'  weekly pick failed, using ranks: {exc}')
    return _fallback_top(items, k)


def render_weekly(top, rest, week_start) -> str:
    e = html.escape
    week_end = week_start + timedelta(days=6)
    parts = [f'<p>The {len(top)} AI and machine-learning stories that mattered most in the week of '
             f'{week_start.strftime("%d %b")} – {week_end.strftime("%d %b %Y")}, picked from the daily digests. '
             f'Each item links to its source.</p>', f'<h2>{WEEKLY_TOP_TITLE}</h2>']
    for it in top:
        parts += render_item(it, show_day=True)
    if rest:
        parts.append('<h2>Also this week</h2><ul>')
        for it in rest[:15]:
            topic = f' <em>· {e(it["topic"])}</em>' if it.get('topic') else ''
            parts.append(f'<li><a href="{e(it["url"])}" target="_blank">{e(it["title"])}</a> '
                         f'<em>({e(it["source"])})</em>{topic}</li>')
        parts.append('</ul>')
    days = sorted({i['day'] for i in top + rest})
    links = ' · '.join(
        f'<a href="{reverse("stories:story_detail", args=[f"ai-ml-digest-{d.isoformat()}"])}">'
        f'{d.strftime("%a %d %b")}</a>' for d in days)
    if links:
        parts.append(f'<p><strong>The daily digests:</strong> {links}</p>')
    parts.append(DISCLAIMER)
    return '\n'.join(parts)


def make_weekly(week_start, dry_run=False, log=print):
    """Roundup of the week starting on Monday week_start. Returns (story or None, top items)."""
    from .models import Story
    items = _week_items(week_start)
    log(f'week of {week_start}: {len(items)} item(s)')
    if len(items) < 3:
        return None, []
    patterns = _walkthrough_patterns()
    top = pick_weekly(items, log=log)
    for it in top:
        it['learn'] = learn_links(it, patterns)
    log('top: ' + '; '.join(i['title'][:60] for i in top))
    if dry_run:
        return None, top
    rest = [i for i in items if i not in top]
    week_end = week_start + timedelta(days=6)
    title = f'AI & ML Weekly — {week_start.strftime("%d %b")} – {week_end.strftime("%d %b %Y")}'
    story, _ = Story.objects.update_or_create(
        slug=f'ai-weekly-{week_start.isoformat()}',
        defaults=dict(author=_author(), title=title,
                      excerpt=f'The week\'s top {len(top)} of {len(items)} items. Top: {top[0]["title"]}'[:290],
                      content=render_weekly(top, rest, week_start), status=Story.Status.PUBLISHED,
                      published_at=timezone.now()))
    _tag(story, ['AI News', 'Weekly'] + sorted({i['topic'] for i in top if i.get('topic')}))
    return story, top


# ── schedule ─────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_last_check = 0.0


def _retry_due(rec) -> bool:
    if rec is None:
        return True
    if rec.status in ('done', 'empty'):
        return False
    if rec.status == 'running':
        return timezone.now() - rec.updated_at > timedelta(minutes=30)
    return rec.attempts < 3 and timezone.now() - rec.updated_at > timedelta(hours=1)


def is_due(now=None) -> bool:
    from .models import DailyDigest
    if not getattr(settings, 'NEWS_DIGEST_ENABLED', True):
        return False
    local = (now or timezone.now()).astimezone(HELSINKI)
    if local.hour < getattr(settings, 'NEWS_DIGEST_HOUR', 7):
        return False
    return _retry_due(DailyDigest.objects.filter(date=local.date()).first())


def last_week_start(now=None):
    """Monday of the previous (complete) week, Helsinki time."""
    local = (now or timezone.now()).astimezone(HELSINKI).date()
    return local - timedelta(days=local.weekday() + 7)


def is_weekly_due(now=None) -> bool:
    """Monday–Wednesday, an hour after the daily digest, once per week."""
    from .models import WeeklyDigest
    if not getattr(settings, 'NEWS_DIGEST_ENABLED', True):
        return False
    local = (now or timezone.now()).astimezone(HELSINKI)
    if local.weekday() > 2 or local.hour < getattr(settings, 'NEWS_DIGEST_HOUR', 7) + 1:
        return False
    return _retry_due(WeeklyDigest.objects.filter(week_start=last_week_start(now)).first())


def _run(rec, make, log):
    rec.status, rec.attempts = 'running', rec.attempts + 1
    rec.save(update_fields=['status', 'attempts', 'updated_at'])
    lines = []

    def say(msg):
        lines.append(str(msg))
        if log:
            log(msg)

    try:
        story, items = make(say)
        rec.story = story
        if hasattr(rec, 'items'):
            rec.items = len(items) if story else 0
        rec.status = 'done' if story else 'empty'
    except Exception as exc:
        logger.exception('News digest failed')
        say(f'failed: {type(exc).__name__}: {exc}')
        rec.status = 'failed'
    rec.log = '\n'.join(lines)[-10000:]
    rec.save()
    return rec


def run_today(log=None):
    from .models import DailyDigest
    day = timezone.now().astimezone(HELSINKI).date()
    rec, _ = DailyDigest.objects.get_or_create(date=day)
    return _run(rec, lambda say: make_digest(day, log=say), log)


def run_weekly(week_start=None, log=None):
    from .models import WeeklyDigest
    week_start = week_start or last_week_start()
    rec, _ = WeeklyDigest.objects.get_or_create(week_start=week_start)
    return _run(rec, lambda say: make_weekly(week_start, log=say), log)


def maybe_run() -> bool:
    """Called by the idle worker; checks at most every 10 minutes."""
    global _last_check
    if time.monotonic() - _last_check < 600:
        return False
    _last_check = time.monotonic()
    if not _lock.acquire(blocking=False):
        return False
    try:
        job = run_today if is_due() else run_weekly if is_weekly_due() else None
    except Exception:
        _lock.release()
        raise
    if job is None:
        _lock.release()
        return False

    def work():
        try:
            job()
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='news-digest', daemon=True).start()
    return True
