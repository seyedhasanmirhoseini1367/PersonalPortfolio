"""Monthly auto-update of the Kaggle Winners Archive.

Once a month, find Featured and Research competitions that ended between two
weeks and six months ago, archive the ones not yet in the archive (top-10
leaderboard + published write-ups + learning cards), and re-check recent ones
that had few write-ups (winners often publish weeks after the end).

Render's free plan has no cron, so the content-generation worker thread calls
maybe_run() while idle; it starts a run when one is due (no successful run in
30 days, no attempt in the last 6 hours). `manage.py kaggle_sync` runs it by hand.
"""
import logging
import os
import threading
import time
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

RUN_EVERY = timedelta(days=30)
RETRY_FAILED_RUN_AFTER = timedelta(hours=6)
ENDED_AT_LEAST = timedelta(days=14)    # give winners time to publish
ENDED_AT_MOST = timedelta(days=183)
RECHECK_AFTER = timedelta(days=30)
GOOD_ENOUGH_WRITEUPS = 3
MAX_ATTEMPTS = 3
CATEGORIES = ('featured', 'research')

_lock = threading.Lock()
_last_check = 0.0


def enabled() -> bool:
    if not getattr(settings, 'KAGGLE_AUTO_SYNC', True):
        return False
    has_env = os.environ.get('KAGGLE_USERNAME') and os.environ.get('KAGGLE_KEY')
    has_file = os.path.exists(os.path.expanduser('~/.kaggle/kaggle.json'))
    return bool(has_env or has_file)


def is_due(now=None) -> bool:
    from .models import KaggleSyncRun
    now = now or timezone.now()
    if KaggleSyncRun.objects.filter(status='done', started_at__gte=now - RUN_EVERY).exists():
        return False
    return not KaggleSyncRun.objects.filter(started_at__gte=now - RETRY_FAILED_RUN_AFTER).exists()


def _slug(ref: str) -> str:
    return (ref or '').rstrip('/').split('/')[-1]


def candidates(api, now=None) -> list[dict]:
    """Finished Featured/Research competitions in the time window, oldest first."""
    now = now or timezone.now()
    found = {}
    for category in CATEGORIES:
        resp = api.competitions_list(category=category, sort_by='latestDeadline', page_size=50)
        for c in getattr(resp, 'competitions', None) or []:
            deadline = getattr(c, 'deadline', None)
            if deadline is None:
                continue
            if timezone.is_naive(deadline):
                deadline = timezone.make_aware(deadline, dt_timezone.utc)
            if not (now - ENDED_AT_MOST <= deadline <= now - ENDED_AT_LEAST):
                continue
            slug = _slug(getattr(c, 'ref', ''))
            if slug:
                found[slug] = {'slug': slug, 'title': getattr(c, 'title', '') or slug,
                               'category': getattr(c, 'category', category) or category,
                               'deadline': deadline}
    # Oldest first: they have had the most time to collect write-ups; recent
    # ones are re-checked next month anyway.
    return sorted(found.values(), key=lambda d: d['deadline'])


def _needs_work(item, now) -> bool:
    if item is None:
        return True
    if item.status == item.STATUS_SKIPPED:
        return False
    if item.status == item.STATUS_FAILED:
        return item.attempts < MAX_ATTEMPTS
    # archived: re-check later if it had few write-ups
    return (item.writeups < GOOD_ENOUGH_WRITEUPS
            and (item.last_checked is None or item.last_checked <= now - RECHECK_AFTER))


def run_sync(trigger='auto', limit=None, log=None) -> 'KaggleSyncRun':
    """Find and archive competitions. At most `limit` extractions per run
    (each one costs several free-tier model calls for the learning cards)."""
    from .extractor import KaggleExtractor
    from .models import Competition, ExtractionJob, KaggleSyncItem, KaggleSyncRun

    limit = limit or getattr(settings, 'KAGGLE_AUTO_SYNC_LIMIT', 3)
    run = KaggleSyncRun.objects.create(trigger=trigger)
    lines = []

    def say(msg):
        lines.append(msg)
        if log:
            log(msg)
        KaggleSyncRun.objects.filter(pk=run.pk).update(log='\n'.join(lines)[-20000:])

    processed = 0
    try:
        from kaggle import api
        api.authenticate()
        now = timezone.now()
        found = candidates(api, now)
        say(f'{len(found)} finished Featured/Research competition(s) in the window')
        for cand in found:
            if processed >= limit:
                say(f'Reached the limit of {limit} for this run; the rest come next month.')
                break
            item = KaggleSyncItem.objects.filter(slug=cand['slug']).first()
            if not _needs_work(item, now):
                continue
            item = item or KaggleSyncItem(slug=cand['slug'])
            item.title, item.category, item.deadline = cand['title'], cand['category'], cand['deadline']
            item.attempts += 1
            item.last_checked = now
            say(f'→ {cand["title"]} ({cand["slug"]})')
            job = ExtractionJob.objects.create(url=cand['slug'], slug=cand['slug'], top_n=10)
            job_log = []

            def job_say(msg, job=job, job_log=job_log):
                job_log.append(msg)
                ExtractionJob.objects.filter(pk=job.pk).update(log='\n'.join(job_log))

            try:
                result = KaggleExtractor(url=cand['slug'], top_n=10, log_fn=job_say).run()
                comp = result['competition']
                writeups = comp.solutions.exclude(writeup_content='').count()
                item.status, item.writeups, item.reason = item.STATUS_ARCHIVED, writeups, ''
                ExtractionJob.objects.filter(pk=job.pk).update(
                    status='done', competition=comp, solutions_saved=result['saved'],
                    finished_at=timezone.now())
                say(f'   archived: {result["saved"]} teams, {writeups} write-up(s)')
            except RuntimeError as exc:
                # e.g. no leaderboard (hackathon-style competition): skip for good
                msg = str(exc)
                no_board = 'leaderboard' in msg.lower() or 'not found' in msg.lower()
                item.status = item.STATUS_SKIPPED if no_board else item.STATUS_FAILED
                item.reason = msg[:500]
                ExtractionJob.objects.filter(pk=job.pk).update(status='failed', finished_at=timezone.now())
                say(f'   {"skipped" if no_board else "failed"}: {msg[:200]}')
            except Exception as exc:
                item.status, item.reason = item.STATUS_FAILED, f'{type(exc).__name__}: {exc}'[:500]
                ExtractionJob.objects.filter(pk=job.pk).update(status='failed', finished_at=timezone.now())
                say(f'   failed: {item.reason[:200]}')
            item.save()
            processed += 1
        status = 'done'
    except Exception as exc:
        logger.exception('Kaggle sync failed')
        say(f'Run failed: {type(exc).__name__}: {exc}')
        status = 'failed'
    KaggleSyncRun.objects.filter(pk=run.pk).update(
        status=status, processed=processed, finished_at=timezone.now())
    run.refresh_from_db()
    return run


def maybe_run() -> bool:
    """Called by the idle worker: start a run in the background if one is due.
    Checks the database at most once an hour."""
    global _last_check
    if time.monotonic() - _last_check < 3600:
        return False
    _last_check = time.monotonic()
    if not enabled() or not _lock.acquire(blocking=False):
        return False
    try:
        if not is_due():
            _lock.release()
            return False
    except Exception:
        _lock.release()
        raise

    def work():
        try:
            run_sync('auto')
        finally:
            close_old_connections()
            _lock.release()

    threading.Thread(target=work, name='kaggle-sync', daemon=True).start()
    return True
