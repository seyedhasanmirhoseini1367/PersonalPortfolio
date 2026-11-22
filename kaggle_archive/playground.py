"""Kaggle's monthly Playground Series in the Winners Archive.

Kaggle has run a small practice competition every month since 2021: the
Tabular Playground Series (2021-2022, slugs like
tabular-playground-series-jan-2021) and then the Playground Series, one season
per year (playground-series-s3e1 ... s6e11). Seasons 1 and 2 here stand for the
two Tabular Playground years.

- import_episodes(): list every episode from the Kaggle API and store it as a
  Competition (title, dates, metric, task). Cheap, so the calendar is complete
  right away.
- analyze_next(): fetch the top-10 leaderboard and the published write-ups of
  a few finished episodes (newest first) and build the learning cards. This
  uses free-tier model calls, so it runs a few episodes a day.
- build_year(): "the year at a glance" for a season, from its episodes' lessons.
- maybe_run(): called by the idle worker; does the above once a day.
"""
import json
import logging
import re
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

PG_RE = re.compile(r'playground-series-s(\d+)e(\d+)$')
TPS_RE = re.compile(r'tabular-playground-series-([a-z]{3})-(\d{4})$')
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
TPS_SEASON = {2021: 1, 2022: 2}
WAIT_AFTER_END = timedelta(days=7)   # give winners a week to post write-ups
MAX_ATTEMPTS = 3
YEAR_REBUILD_EVERY = 3               # rebuild a year summary after this many newly analysed episodes

CLASSIFICATION = re.compile(r'auc|roc|area under|receiver operating|accuracy|log ?loss|multiclass|f1|map@|kappa|mcc|'
                            r'matthews|corrcoef|precision|recall|categorization|classification', re.I)
REGRESSION = re.compile(r'rmse|rmsle|mae|mse|r2|r\^2|mape|smape|absolute|squared|regression|pearson', re.I)


def parse_slug(slug: str):
    """slug -> (season, episode, month) for Playground / Tabular Playground slugs, else None.
    Tabular Playground episodes are numbered by month."""
    slug = (slug or '').rstrip('/').split('/')[-1]
    m = PG_RE.search(slug)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    m = TPS_RE.search(slug)
    if m and m.group(1) in MONTHS and int(m.group(2)) in TPS_SEASON:
        month = MONTHS.index(m.group(1)) + 1
        return TPS_SEASON[int(m.group(2))], month, month
    return None


def task_from_metric(metric: str) -> str:
    metric = metric or ''
    if CLASSIFICATION.search(metric):
        return 'classification'
    if REGRESSION.search(metric):
        return 'regression'
    return 'other'


def _date(value):
    if not value:
        return None
    if hasattr(value, 'date'):
        return value.date()
    from django.utils.dateparse import parse_date
    return parse_date(str(value)[:10])


def _api():
    from kaggle import api
    api.authenticate()
    return api


def import_episodes(api=None, log=print) -> int:
    """Store every Playground episode the Kaggle API lists. Returns how many were new."""
    from .extractor import KaggleExtractor
    from .models import Competition
    api = api or _api()
    helper = KaggleExtractor(url='')
    new = 0
    for page in range(1, 30):
        resp = api.competitions_list(category='playground', page=page)
        comps = getattr(resp, 'competitions', None) or []
        if not comps:
            break
        for c in comps:
            slug = (getattr(c, 'ref', '') or '').rstrip('/').split('/')[-1]
            parsed = parse_slug(slug)
            if not parsed:
                continue
            season, episode, _ = parsed
            title = getattr(c, 'title', '') or slug
            tags = ' '.join((t.get('ref', '') if isinstance(t, dict) else getattr(t, 'ref', ''))
                            for t in (getattr(c, 'tags', None) or [])).lower()
            metric = getattr(c, 'evaluation_metric', '') or ''
            defaults = {
                'name': title, 'host': 'Kaggle', 'series': Competition.SERIES_PLAYGROUND,
                'season': season, 'episode': episode, 'evaluation_metric': metric,
                'task': task_from_metric(metric),
                'kaggle_url': getattr(c, 'url', '') or f'https://www.kaggle.com/competitions/{slug}',
                'start_date': _date(getattr(c, 'enabled_date', None)),
                'end_date': _date(getattr(c, 'deadline', None)),
                'num_teams': getattr(c, 'team_count', 0) or 0,
                'description': (getattr(c, 'description', '') or '')[:1000],
            }
            comp = Competition.objects.filter(slug=slug).first()
            if comp is None:
                Competition.objects.create(
                    slug=slug, competition_type=helper._detect_type(tags, title.lower()) if 'tabular' not in tags else 'tabular',
                    domain=helper._detect_domain(tags, title.lower()), **defaults)
                new += 1
            else:
                for k, v in defaults.items():
                    if v not in (None, '') or k in ('series', 'season', 'episode'):
                        setattr(comp, k, v)
                comp.save()
    log(f'playground: {new} new episode(s) imported')
    return new


def pending(now=None):
    """Finished episodes whose winners have not been fetched yet, newest first."""
    from .models import Competition
    today = (now or timezone.now()).date()
    return (Competition.objects.filter(series=Competition.SERIES_PLAYGROUND, analyzed_at__isnull=True,
                                       analysis_attempts__lt=MAX_ATTEMPTS, end_date__lte=today - WAIT_AFTER_END)
            .order_by('-end_date'))


def analyze(comp, log=print) -> bool:
    """Leaderboard + write-ups + learning cards for one episode."""
    from .extractor import KaggleExtractor
    comp.analysis_attempts += 1
    comp.save(update_fields=['analysis_attempts'])
    try:
        KaggleExtractor(url=comp.slug, top_n=10, log_fn=lambda m: None).run()
    except Exception as exc:
        log(f'  {comp.slug}: {exc}')
        return False
    comp.refresh_from_db()
    comp.analyzed_at = timezone.now()
    comp.save(update_fields=['analyzed_at'])
    log(f'  {comp.slug}: {comp.solutions.count()} teams, '
        f'{comp.solutions.exclude(writeup_content="").count()} write-up(s)')
    return True


def analyze_next(limit=None, log=print) -> int:
    limit = limit if limit is not None else getattr(settings, 'KAGGLE_PLAYGROUND_DAILY', 3)
    done = 0
    for comp in list(pending()[:limit]):
        done += analyze(comp, log)
    return done


# ── "the year at a glance" ───────────────────────────────────────────────────

def calendar_month(comp):
    """(year, month) an episode belongs to: the middle of its run (an episode that opens on
    31 December belongs to January)."""
    start, end = comp.start_date, comp.end_date
    d = start + (end - start) / 2 if start and end else (start or end)
    return (d.year, d.month) if d else (None, None)


def season_year(season):
    from collections import Counter
    from .models import Competition
    years = Counter(calendar_month(c)[0] for c in
                    Competition.objects.filter(series=Competition.SERIES_PLAYGROUND, season=season))
    years.pop(None, None)
    return years.most_common(1)[0][0] if years else None


def build_year(season, log=print, force=False):
    """Recurring winning ideas and lessons across a season's analysed episodes."""
    from .models import Competition, PlaygroundYear
    from .summarizer import _generate, _numbers
    comps = list(Competition.objects.filter(series=Competition.SERIES_PLAYGROUND, season=season)
                 .exclude(insights__isnull=True).order_by('episode'))
    comps = [c for c in comps if (c.insights or {}).get('lessons') or (c.insights or {}).get('common')]
    rec = PlaygroundYear.objects.filter(season=season).first()
    if len(comps) < 3:
        return rec
    if rec and not force:
        season_total = Competition.objects.filter(series=Competition.SERIES_PLAYGROUND, season=season).count()
        grown = len(comps) - rec.based_on
        if grown <= 0 or (grown < YEAR_REBUILD_EVERY and len(comps) < season_total):
            return rec   # rebuild after a few more episodes, or once the season is complete
    blocks = []
    for c in comps:
        ins = c.insights or {}
        common = '; '.join(x.get('idea', '') for x in ins.get('common', []) if isinstance(x, dict))
        blocks.append(f'E{c.episode} {c.name} ({c.evaluation_metric}): shared by winners: {common} | '
                      f'lessons: ' + '; '.join(ins.get('lessons', [])))
    prompt = f"""Below are the Kaggle Playground Series episodes of one year, each with what the top teams
had in common and the lessons from their write-ups.

{chr(10).join(blocks)}

Return JSON:
- "recurring": 4-6 short items: approaches that won again and again this year (e.g. a model family, a validation habit)
- "lessons": 3 short lessons a learner should take from the whole year
- "surprise": 1 sentence on something that worked unexpectedly or changed during the year (empty if nothing)
Use ONLY the text above. Return ONLY the JSON object."""
    try:
        data = _generate(prompt)
    except Exception as exc:
        log(f'  year summary failed for season {season}: {exc}')
        return rec
    known = set()
    for b in blocks:
        known |= _numbers(b)
    ok = lambda t: isinstance(t, str) and t.strip() and _numbers(t) <= known
    summary = {
        'recurring': [x.strip() for x in data.get('recurring') or [] if ok(x)][:6],
        'lessons': [x.strip() for x in data.get('lessons') or [] if ok(x)][:3],
        'surprise': data.get('surprise', '').strip() if ok(data.get('surprise')) else '',
    }
    if not summary['recurring'] and not summary['lessons']:
        return rec
    rec, _ = PlaygroundYear.objects.update_or_create(season=season, defaults={
        'year': season_year(season) or 0, 'summary': summary, 'based_on': len(comps),
        'generated_at': timezone.now()})
    log(f'  year summary: season {season} from {len(comps)} episode(s)')
    return rec


# ── daily schedule ───────────────────────────────────────────────────────────

_lock = threading.Lock()
_last_check = 0.0


def is_due(now=None) -> bool:
    from .auto import enabled
    from .models import KaggleSyncRun
    if not enabled() or not getattr(settings, 'KAGGLE_PLAYGROUND_SYNC', True):
        return False
    now = now or timezone.now()
    return not KaggleSyncRun.objects.filter(trigger='playground', started_at__gte=now - timedelta(hours=20)).exists()


def run_daily(log=None):
    from .models import Competition, KaggleSyncRun
    run = KaggleSyncRun.objects.create(trigger='playground')
    lines = []

    def say(msg):
        lines.append(str(msg))
        if log:
            log(msg)

    status, processed = 'done', 0
    try:
        api = _api()
        import_episodes(api, log=say)
        processed = analyze_next(log=say)
        seasons = (Competition.objects.filter(series=Competition.SERIES_PLAYGROUND)
                   .values_list('season', flat=True).distinct())
        for season in sorted({s for s in seasons if s}, reverse=True):
            build_year(season, log=say)
    except Exception as exc:
        logger.exception('Playground sync failed')
        say(f'failed: {type(exc).__name__}: {exc}')
        status = 'failed'
    KaggleSyncRun.objects.filter(pk=run.pk).update(status=status, processed=processed, finished_at=timezone.now(),
                                                   log='\n'.join(lines)[-20000:])
    return run


def maybe_run() -> bool:
    """Called by the idle worker; checks at most hourly, runs at most daily."""
    global _last_check
    if time.monotonic() - _last_check < 3600:
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
            run_daily()
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='kaggle-playground', daemon=True).start()
    return True
