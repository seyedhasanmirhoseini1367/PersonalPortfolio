"""Database-backed queue for content generation jobs.

Jobs are rows in GenerationJob with status "pending". One worker thread in
the web process takes them in order, runs the pipeline, and records each
step (progress_step / progress_label / heartbeat_at) so the waiting page can
show real progress. Render's free plan has no separate worker service, so the
thread lives in the gunicorn process (started from wsgi.py).

Because the queue is in the database, nothing is lost when the process
restarts: a job whose heartbeat went quiet is put back in the queue once,
then marked failed with a clear message, instead of staying "running" forever.
On PostgreSQL, SELECT ... FOR UPDATE SKIP LOCKED keeps two workers from
taking the same job.
"""
import logging
import os
import socket
import sys
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.db.models import F, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)   # no heartbeat for this long = interrupted
# A job taken by another process (e.g. the instance before a deploy) is
# requeued sooner: that process is most likely gone. Steps report at least
# every couple of minutes, so a job still alive elsewhere is not taken twice.
STALE_AFTER_OTHER = timedelta(minutes=3)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"[:80]
MAX_ATTEMPTS = 2                      # first run + one retry after an interruption
POLL_SECONDS = 10

_wake = threading.Event()
_start_lock = threading.Lock()
_started = False


def worker_enabled() -> bool:
    if 'test' in sys.argv:
        return False
    return bool(getattr(settings, 'CONTENT_GENERATOR_RUN_WORKER', True))


def start() -> None:
    """Start the worker thread once per process (no-op in tests / when disabled)."""
    global _started
    if not worker_enabled():
        return
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name='generation-worker', daemon=True).start()
    logger.info('Content generation worker started')


def wake() -> None:
    """Tell the worker a new job is waiting (it also polls on its own)."""
    _wake.set()


def enqueue(job) -> None:
    """Called after a pending job is saved."""
    start()
    wake()


def recover_stale(now=None) -> int:
    """Requeue (or fail) running jobs whose worker stopped reporting."""
    from .models import GenerationJob
    now = now or timezone.now()
    mine, others = now - STALE_AFTER, now - STALE_AFTER_OTHER
    stale = GenerationJob.objects.filter(status=GenerationJob.STATUS_RUNNING).filter(
        Q(heartbeat_at__lt=mine)
        | (~Q(claimed_by=WORKER_ID) & Q(heartbeat_at__lt=others))
        | Q(heartbeat_at__isnull=True, updated_at__lt=others))
    count = 0
    for job in stale:
        if job.attempts < MAX_ATTEMPTS:
            GenerationJob.objects.filter(pk=job.pk, status=GenerationJob.STATUS_RUNNING).update(
                status=GenerationJob.STATUS_PENDING, progress_step=0,
                progress_label='Restarting after an interruption')
        else:
            GenerationJob.objects.filter(pk=job.pk, status=GenerationJob.STATUS_RUNNING).update(
                status=GenerationJob.STATUS_FAILED,
                error_message='Generation was interrupted (the server restarted). Please try again.')
        count += 1
    if count:
        logger.warning('Recovered %d interrupted generation job(s)', count)
    return count


def claim_next():
    """Mark the oldest pending job as running and return its id, or None."""
    from .models import GenerationJob
    with transaction.atomic():
        qs = GenerationJob.objects.filter(status=GenerationJob.STATUS_PENDING).order_by('created_at')
        if connection.features.has_select_for_update_skip_locked:
            qs = qs.select_for_update(skip_locked=True)
        job = qs.first()
        if job is None:
            return None
        now = timezone.now()
        GenerationJob.objects.filter(pk=job.pk).update(
            status=GenerationJob.STATUS_RUNNING, started_at=now, heartbeat_at=now,
            attempts=F('attempts') + 1, progress_step=0, progress_label='Starting',
            claimed_by=WORKER_ID)
        return job.pk


def run_job(job_id) -> None:
    from .models import GenerationJob
    from .views import _run_pipeline_now

    def report(step: int, label: str) -> None:
        GenerationJob.objects.filter(pk=job_id).update(
            progress_step=step, progress_label=label[:120], heartbeat_at=timezone.now())

    job = GenerationJob.objects.filter(pk=job_id).only('seo_params').first()
    if job is None:
        return
    _run_pipeline_now(str(job_id), job.seo_params or {}, progress=report)


def run_pending(limit=None) -> int:
    """Process queued jobs now (used by tests and the management command)."""
    done = 0
    while limit is None or done < limit:
        job_id = claim_next()
        if job_id is None:
            break
        run_job(job_id)
        done += 1
    return done


def _loop() -> None:
    time.sleep(3)   # let the server finish starting
    while True:
        try:
            close_old_connections()
            recover_stale()
            job_id = claim_next()
            if job_id is None:
                _wake.wait(timeout=POLL_SECONDS)
                _wake.clear()
                continue
            run_job(job_id)
        except Exception:
            logger.exception('Content generation worker error')
            time.sleep(5)
        finally:
            close_old_connections()
