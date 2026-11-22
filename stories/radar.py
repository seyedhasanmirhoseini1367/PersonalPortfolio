"""Repo Radar: a weekly, personal list of GitHub projects worth a look.

Once a week (Monday after 09:00 Helsinki) collect candidate repositories
- from GitHub's weekly Trending pages (which state the stars gained this week), and
- from the GitHub search API for the configured topics (recently active, many stars),
keep the ones that match the topics, rank them by stars gained this week (our
own snapshot from last week where Trending gives no number), and ask the model
for two lines per repo: what it is, and why it is useful for the owner's
profile. The list goes to the owner's private Telegram chat (with a button per
repo to add it to the next news digest) and to the News desk page. Nothing is
posted publicly.
"""
import html
import json
import logging
import re
import threading
import time
import urllib.request
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)
HELSINKI = ZoneInfo('Europe/Helsinki')
UA = 'Mozilla/5.0 (compatible; HasanAI-radar/1.0; +https://hasanai.net/)'
TRENDING_PAGES = ['https://github.com/trending/python?since=weekly',
                  'https://github.com/trending/jupyter-notebook?since=weekly',
                  'https://github.com/trending?since=weekly']
RESEND_AFTER = timedelta(days=60)
MIN_STARS = 150

# Extra words that count as a match for a topic.
SYNONYMS = {
    'rag': [r'\brag\b', r'retrieval'],
    'mlops': [r'mlops', r'deploy', r'serving', r'monitoring', r'pipeline', r'experiment tracking'],
    'llm': [r'\bllms?\b', r'language model'],
    'ai-agents': [r'\bagents?\b', r'agentic'],
    'llm-inference': [r'inference', r'serving', r'quantiz', r'vllm', r'\bgguf\b'],
    'machine-learning': [r'machine learning', r'\bml\b'],
    'kaggle': [r'kaggle', r'competition'],
    'tabular': [r'tabular', r'xgboost', r'lightgbm', r'catboost', r'gradient boosting'],
    'deep-learning': [r'deep learning', r'neural'],
    'computer-vision': [r'computer vision', r'\bvision\b', r'image'],
}


def _get(url, timeout=20, accept='*/*'):
    headers = {'User-Agent': UA, 'Accept': accept}
    token = getattr(settings, 'GITHUB_TOKEN', '')
    if token and 'api.github.com' in url:
        headers['Authorization'] = f'Bearer {token}'
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read(3_000_000)


def _plain(fragment):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', fragment or ''))).strip()


def parse_trending(page: str) -> list[dict]:
    """GitHub Trending HTML -> [{full_name, description, weekly_gain, stars}]."""
    out = []
    for block in page.split('<article class="Box-row">')[1:]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([\w.-]+/[\w.-]+)"', block)
        if not m:
            continue
        desc = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', block, re.S)
        gain = re.search(r'([\d,]+)\s+stars? this week', block)
        total = re.search(r'/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', block, re.S)
        out.append({'full_name': m.group(1), 'description': _plain(desc.group(1)) if desc else '',
                    'weekly_gain': int(gain.group(1).replace(',', '')) if gain else 0,
                    'stars': int(total.group(1).replace(',', '')) if total else 0})
    return out


def topic_patterns(topics):
    pats = {}
    for t in topics:
        words = [r'\b' + re.escape(t).replace(r'\-', r'[- ]?') + r'\b'] + SYNONYMS.get(t, [])
        pats[t] = re.compile('|'.join(words), re.I)
    return pats


def matched_topics(item, pats, repo_topics=()):
    text = f"{item['full_name'].replace('/', ' ')} {item.get('description', '')}"
    return [t for t, p in pats.items() if t in repo_topics or p.search(text)]


def collect(cfg, log=print) -> dict:
    """{full_name: candidate} from Trending and the search API."""
    found = {}
    for url in TRENDING_PAGES:
        try:
            for it in parse_trending(_get(url).decode('utf-8', 'replace')):
                prev = found.get(it['full_name'])
                if not prev or it['weekly_gain'] > prev['weekly_gain']:
                    found[it['full_name']] = {**it, 'topics': [], 'source': 'trending'}
        except Exception as exc:
            log(f'  trending {url}: {exc}')
    since = (timezone.now() - timedelta(days=14)).date().isoformat()
    for i, topic in enumerate(cfg.topic_list()):
        if i:
            time.sleep(7)   # the search API allows 10 requests a minute without a token
        try:
            data = json.loads(_get(f'https://api.github.com/search/repositories?q=topic:{topic}+pushed:%3E{since}'
                                   f'+stars:%3E%3D{MIN_STARS}&sort=stars&order=desc&per_page=30',
                                   accept='application/vnd.github+json'))
        except Exception as exc:
            log(f'  search {topic}: {exc}')
            continue
        for r in data.get('items', []):
            from .digest import _looks_like_star_spam
            if r.get('fork') or r.get('archived') or _looks_like_star_spam(r):
                continue
            name = r['full_name']
            cand = found.setdefault(name, {'full_name': name, 'description': r.get('description') or '',
                                           'weekly_gain': 0, 'stars': r.get('stargazers_count', 0),
                                           'topics': [], 'source': 'search', 'created_at': r.get('created_at')})
            cand['topics'] = sorted(set(cand['topics']) | set(r.get('topics') or []))
            cand['stars'] = max(cand['stars'], r.get('stargazers_count', 0))
            cand.setdefault('created_at', r.get('created_at'))
    log(f'  {len(found)} candidate repo(s)')
    return found


def recent_stars(full_name, stars, days=7) -> int:
    """Stars a repo got in the last `days`, counted from the newest stargazers (GitHub keeps star dates).
    0 when unknown (very large repos only expose their first 40k stargazers)."""
    import math
    if stars <= 0 or stars > 40_000:
        return 0
    since = timezone.now() - timedelta(days=days)
    from .digest import _date
    count, page = 0, max(1, math.ceil(stars / 100))
    for _ in range(3):
        try:
            rows = json.loads(_get(f'https://api.github.com/repos/{full_name}/stargazers?per_page=100&page={page}',
                                   accept='application/vnd.github.star+json'))
        except Exception:
            break
        dates = [_date(r.get('starred_at') or '') for r in rows if isinstance(r, dict)]
        fresh = [d for d in dates if d and d >= since]
        count += len(fresh)
        if len(fresh) < len(dates) or page == 1:
            break
        page -= 1
    return count


def spread(cands, topics, limit) -> list[dict]:
    """Best-growing repos, taken in turns from each topic so one busy topic does not fill the list."""
    out, seen = [], set()
    queues = {t: [c for c in cands if t in c['matched']] for t in topics}
    while len(out) < limit and any(queues.values()):
        for t in topics:
            while queues[t] and queues[t][0]['full_name'] in seen:
                queues[t].pop(0)
            if queues[t] and len(out) < limit:
                c = queues[t].pop(0)
                seen.add(c['full_name'])
                out.append(c)
    return out


def rank(found, cfg, now=None, measure=25) -> list[dict]:
    """Relevant candidates with their weekly growth, best first. Updates the star snapshots."""
    from .models import RadarRepo
    now = now or timezone.now()
    pats = topic_patterns(cfg.topic_list())
    out = []
    # Repos the radar has never seen (no snapshot yet) and Trending gave no number for:
    # count their recent stargazers directly, for the most-starred relevant ones.
    unseen = sorted((c for c in found.values() if not c['weekly_gain'] and matched_topics(c, pats, c.get('topics', []))
                     and not RadarRepo.objects.filter(full_name=c['full_name'], checked_at__isnull=False).exists()),
                    key=lambda c: -c['stars'])
    for c in unseen[:measure]:
        c['weekly_gain'] = recent_stars(c['full_name'], c['stars'])
    for name, c in found.items():
        hit = matched_topics(c, pats, c.get('topics', []))
        rec = RadarRepo.objects.filter(full_name=name).first()
        gain = c['weekly_gain']
        if not gain and rec and rec.checked_at and rec.stars and now - rec.checked_at >= timedelta(days=5):
            days = max((now - rec.checked_at).days, 1)
            gain = int((c['stars'] - rec.stars) * 7 / days)   # our own snapshot, scaled to a week
        if not gain and c.get('created_at'):
            from .digest import _date
            created = _date(c['created_at'])
            if created and now - created < timedelta(days=21):
                gain = c['stars']                              # new this month: all its stars are recent
        rec = rec or RadarRepo(full_name=name)
        if not rec.checked_at or now - rec.checked_at >= timedelta(days=5):
            rec.stars, rec.checked_at = c['stars'] or rec.stars, now
        rec.description = (c.get('description') or rec.description)[:1000]
        rec.weekly_gain = gain
        rec.save()
        if not hit or gain <= 0:
            continue
        if rec.sent_at and now - rec.sent_at < RESEND_AFTER:
            continue
        out.append({**c, 'weekly_gain': gain, 'matched': hit, 'id': rec.pk})
    out.sort(key=lambda c: -c['weekly_gain'])
    return out


REPO_STYLES = [
    'Open with the pain it removes, then what it does.',
    'Open with what you can build or run with it today.',
    'Open with a short question a practitioner might ask, then answer it.',
    'Open with how it works under the hood, in plain words.',
    'Open by comparing it with the usual way of doing this.',
    'Open with who made it and who it is for.',
]
REPO_ANGLES = ['Worth a look', 'Use it for', 'Try it if', 'The catch', 'Learn from it', 'Who it’s for', 'Under the hood']
_CMD = re.compile(r'^\s*(?:\$\s*)?((?:pip3?|uv|pipx|conda|npm|npx|pnpm|yarn|docker|brew|cargo|go)\s+'
                  r'(?:install|add|run|pull|get|tool install)\b[^\n`#|]{1,90})', re.M)


def quick_start(full_name) -> str:
    """The first install / run command in the README, copied verbatim (or '')."""
    try:
        readme = _get(f'https://raw.githubusercontent.com/{full_name}/HEAD/README.md', timeout=10).decode('utf-8', 'replace')
    except Exception:
        return ''
    m = _CMD.search(readme)
    return m.group(1).strip().rstrip('\\').strip()[:200] if m else ''


def describe(cands, cfg, log=print) -> list[dict]:
    """Two short lines per repo, written for the owner's profile; drops the irrelevant ones."""
    from content_generator.pipeline.agents.gemini_client import generate
    from .digest import _grounded, github_text
    if not cands:
        return []
    from .digest import TOPICS, _topic
    for c in cands:
        c['text'] = github_text(c['full_name'], c.get('description', ''))[:1200]
    shift = timezone.now().isocalendar()[1]   # a different style rotation every week
    listing = '\n\n'.join(f'[{i}] {c["full_name"]} (+{c["weekly_gain"]} stars this week; topics: {", ".join(c["matched"])})\n'
                          f'STYLE: {REPO_STYLES[(shift + i) % len(REPO_STYLES)]}\n{c["text"]}' for i, c in enumerate(cands))
    angles = ', '.join(f'"{a}"' for a in REPO_ANGLES)
    topics = ', '.join(f'"{t}"' for t in TOPICS)
    prompt = f"""You pick GitHub projects for one engineer. Their profile:
{cfg.profile}

Write like a good newsletter by a person: every repository phrased differently, never the same template twice.
For each repository below write:
- "what": 1-2 plain sentences on what it is / does, following its STYLE
- "for_you": one sentence: how this engineer could use it or what they could learn from it
- "angle": the label that fits best for the public line, one of {angles}; use different labels across repositories
- "why": one sentence for a public news post that fits that label (e.g. "The catch" = a limitation stated in the text)
- "topic": exactly one of {topics}
- "relevant": true if it is genuinely useful for this profile, false if it is off-topic, a list of links, or hype

Use ONLY the text given for each repository; add no numbers or claims that are not in it.

{listing}

Return JSON: {{"items": [{{"n": <index>, "what": str, "for_you": str, "angle": str, "why": str, "topic": str, "relevant": bool}}, ...]}}
Return ONLY the JSON."""
    try:
        data = json.loads(generate(prompt))
    except Exception as exc:
        log(f'  summaries failed ({exc}); using the descriptions')
        return [{**c, 'what': c.get('description', ''), 'for_you': ''} for c in cands[:cfg.max_items]]
    rows = data.get('items', data) if isinstance(data, dict) else data
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            c = cands[int(row.get('n'))]
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        if row.get('relevant') is False:
            continue
        source = c['text'] + ' ' + c['full_name']
        c['what'] = _grounded(str(row.get('what', '')), source) or c.get('description', '')
        c['for_you'] = _grounded(str(row.get('for_you', '')), source)
        c['why'] = _grounded(str(row.get('why', '')), source)
        c['angle'] = next((a for a in REPO_ANGLES if a.lower() == str(row.get('angle', '')).strip().lower()), REPO_ANGLES[0])
        c['topic'] = _topic(row.get('topic'), {'title': c['full_name'], 'text': c['text']})
        out.append(c)
    out.sort(key=lambda c: -c['weekly_gain'])
    return out[:cfg.max_items]


# ── delivery ─────────────────────────────────────────────────────────────────

def telegram_text(repos, day) -> str:
    e = lambda s: html.escape(s or '', quote=True)
    lines = [f'🛰 <b>Repo Radar</b> — week of {day:%d %b %Y}', '<i>GitHub projects that grew fastest this week, '
             'picked for your topics.</i>', '']
    for i, r in enumerate(repos, 1):
        block = [f'{i}. <a href="{e(r.url)}">{e(r.full_name)}</a>  ⭐ +{r.weekly_gain:,} this week', e(r.what)]
        if r.for_you:
            block.append(f'→ {e(r.for_you)}')
        if len('\n'.join(lines + block)) > 3800:
            break
        lines += block + ['']
    lines.append('Tap ➕ to add one to the next AI news digest.')
    return '\n'.join(lines)


def send_to_owner(repos, day):
    from . import telegram
    from .models import TelegramConfig
    cfg = TelegramConfig.get()
    if not telegram.configured() or not cfg.admin_chat_id or not repos:
        return False
    buttons = [{'text': f'➕ {i}', 'callback_data': f'rr:add:{r.pk}'} for i, r in enumerate(repos, 1)]
    keyboard = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    keyboard.append([{'text': '📋 Open the News desk', 'url': telegram.review_url()}])
    telegram.api('sendMessage', chat_id=cfg.admin_chat_id, text=telegram_text(repos, day), parse_mode='HTML',
                 link_preview_options={'is_disabled': True}, reply_markup={'inline_keyboard': keyboard})
    return True


def add_to_digest(repo) -> bool:
    """Queue a radar repo for the next daily digest (as an editor's link)."""
    from .models import SuggestedLink
    if repo.added:
        return False
    note = ' '.join(x for x in (repo.what, repo.for_you) if x)[:300]
    SuggestedLink.objects.create(url=repo.url, note=note)
    repo.added = True
    repo.save(update_fields=['added'])
    return True


# ── public post on AI News ───────────────────────────────────────────────────

MIN_PUBLIC = 3


def render_post(repos, day) -> str:
    from .digest import DISCLAIMER, _topic_url
    e = html.escape
    parts = ['<p>The open-source AI and machine-learning projects that gained the most GitHub stars this week, '
             'with what each one does. Every item links to its repository.</p>', '<h2>Trending on GitHub this week</h2>']
    for r in repos:
        parts.append(f'<h3><a href="{e(r.url)}" target="_blank">{e(r.full_name)}</a></h3>')
        topic = r.topic or 'Tools & Open Source'
        parts.append(f'<p class="digest-meta"><a class="digest-topic" href="{_topic_url(topic)}">{e(topic)}</a></p>')
        parts.append(f'<p>{e(r.what or r.description)}</p>')
        if r.why:
            parts.append(f'<p><strong>{e(r.angle or REPO_ANGLES[0])}:</strong> {e(r.why)}</p>')
        if r.try_cmd:
            parts.append(f'<p class="digest-try"><strong>Quick start:</strong> <code>{e(r.try_cmd)}</code></p>')
        parts.append(f'<p><em>Source: <a href="{e(r.url)}" target="_blank">GitHub</a> · +{r.weekly_gain:,} stars this week'
                     f' · {r.stars:,} in total</em></p>')
    parts.append(DISCLAIMER)
    return '\n'.join(parts)


def publish(repos, day):
    """The weekly "Open-Source Radar" post on AI News (also drafted for the Telegram channel)."""
    from .digest import _author, _tag
    from .models import DigestItem, Story
    repos = [r for r in repos if r.what or r.description]
    if len(repos) < MIN_PUBLIC:
        return None
    story, _ = Story.objects.update_or_create(
        slug=f'ai-repos-{day.isoformat()}',
        defaults=dict(author=_author(), title=f'Open-Source Radar — week of {day:%d %b %Y}',
                      excerpt=f'{len(repos)} trending AI repos this week. Top: {repos[0].full_name}'[:290],
                      content=render_post(repos, day), status=Story.Status.PUBLISHED, published_at=timezone.now()))
    _tag(story, ['AI News', 'Open Source'] + sorted({r.topic or 'Tools & Open Source' for r in repos}))
    for r in repos:   # also stops the daily digest repeating them, and gives the Telegram post its text
        DigestItem.objects.update_or_create(url=r.url, defaults={
            'title': r.full_name, 'source': 'GitHub', 'digest_date': day, 'section': 'repos',
            'topic': r.topic or 'Tools & Open Source', 'summary': r.what or r.description, 'why': r.why,
            'angle': r.angle, 'score': 0})
    try:
        from .telegram import configured, queue_post
        if configured():
            queue_post(story)   # draft for the channel; sent only after approval
    except Exception as exc:
        logger.warning('Telegram draft for the radar failed: %s', exc)
    return story


# ── run & schedule ───────────────────────────────────────────────────────────

def rewrite_latest(log=print):
    """Write the last run's repos again (new wording, labels, quick start) and republish its post."""
    from .models import RadarConfig, RadarRepo, RadarRun
    last = RadarRun.objects.filter(status='done').first()
    if not last or not last.picked:
        return None
    found = {r.pk: r for r in RadarRepo.objects.filter(pk__in=last.picked)}
    repos = [found[i] for i in last.picked if i in found]
    cfg = RadarConfig.get()
    cands = [{'full_name': r.full_name, 'description': r.description, 'weekly_gain': r.weekly_gain,
              'matched': [], 'id': r.pk} for r in repos]
    for c in describe(cands, cfg, log):
        r = found[c['id']]
        r.what, r.for_you = c.get('what', r.what)[:600], c.get('for_you', r.for_you)[:600]
        r.why, r.angle, r.topic = c.get('why', '')[:600], c.get('angle', '')[:40], c.get('topic', '')[:40]
        r.try_cmd = quick_start(r.full_name)
        r.save(update_fields=['what', 'for_you', 'why', 'angle', 'topic', 'try_cmd'])
    day = last.started_at.astimezone(HELSINKI).date()
    return publish([found[i] for i in last.picked if i in found], day)


def run(log=None):
    from .models import RadarConfig, RadarRepo, RadarRun
    cfg = RadarConfig.get()
    rec = RadarRun.objects.create()
    lines = []

    def say(msg):
        lines.append(str(msg))
        if log:
            log(msg)

    try:
        cands = rank(collect(cfg, say), cfg)
        say(f'{len(cands)} relevant repo(s) grew this week')
        picked = describe(spread(cands, cfg.topic_list(), cfg.max_items * 2), cfg, say)
        now = timezone.now()
        repos = []
        for c in picked:
            r = RadarRepo.objects.get(pk=c['id'])
            r.what, r.for_you, r.sent_at = c.get('what', '')[:600], c.get('for_you', '')[:600], now
            r.why, r.angle, r.topic = c.get('why', '')[:600], c.get('angle', '')[:40], c.get('topic', '')[:40]
            r.try_cmd = quick_start(r.full_name)
            r.save(update_fields=['what', 'for_you', 'why', 'angle', 'topic', 'try_cmd', 'sent_at'])
            repos.append(r)
        rec.picked = [r.pk for r in repos]
        try:
            story = publish(repos, now.astimezone(HELSINKI).date())
            say(f'published {story.slug}' if story else 'not published (fewer than 3 repos)')
        except Exception as exc:
            say(f'publishing failed: {exc}')
        try:
            sent = send_to_owner(repos, now.astimezone(HELSINKI).date())
            say('sent to your Telegram' if sent else 'not sent to Telegram (not linked or nothing to send)')
        except Exception as exc:
            say(f'telegram failed: {exc}')
        rec.status = 'done'
    except Exception as exc:
        logger.exception('Repo radar failed')
        say(f'failed: {type(exc).__name__}: {exc}')
        rec.status = 'failed'
    rec.log = '\n'.join(lines)[-10000:]
    rec.save()
    return rec


def is_due(now=None) -> bool:
    from .models import RadarConfig, RadarRun
    if not RadarConfig.get().enabled:
        return False
    now = now or timezone.now()
    local = now.astimezone(HELSINKI)
    if local.weekday() != 0 or local.hour < 9:
        return False
    return not RadarRun.objects.filter(started_at__gte=now - timedelta(days=5)).exists()


_lock = threading.Lock()
_last_check = 0.0


def start_in_background():
    if not _lock.acquire(blocking=False):
        return False

    def work():
        try:
            run()
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='repo-radar', daemon=True).start()
    return True


def maybe_run() -> bool:
    """Called by the idle worker; checks at most every 30 minutes."""
    global _last_check
    if time.monotonic() - _last_check < 1800:
        return False
    _last_check = time.monotonic()
    return is_due() and start_in_background()
