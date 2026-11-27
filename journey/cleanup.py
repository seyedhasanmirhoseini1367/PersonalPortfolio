"""Housekeeping for LearningJourney, run by the site's background worker.

Published lessons and everyone's progress are never touched: spaced repetition needs
them for months. Only leftovers go:
  - lessons whose build failed, after FAILED_DAYS
  - drafts nobody published, after DRAFT_DAYS
  - lessons stuck in "building" (the server restarted mid-build) are marked failed
    after STUCK_MINUTES, so the author sees "Try again" instead of a spinner
"""
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import LessonPack, PendingUpload

logger = logging.getLogger(__name__)

FAILED_DAYS = getattr(settings, 'JOURNEY_KEEP_FAILED_DAYS', 7)
DRAFT_DAYS = getattr(settings, 'JOURNEY_KEEP_DRAFT_DAYS', 30)
STUCK_MINUTES = 60
CHECK_EVERY = 3600

_last_check = None   # None: never checked in this process, so the first call runs


def run(now=None):
    """Do one cleanup pass. Returns counts, for logs and tests."""
    now = now or timezone.now()
    stuck = (LessonPack.objects.filter(status=LessonPack.PROCESSING,
                                       created_at__lt=now - timedelta(minutes=STUCK_MINUTES))
             .update(status=LessonPack.FAILED, progress_note='',
                     error='Building this lesson was interrupted. Press “Try again”, or add it again.'))
    failed, _ = LessonPack.objects.filter(status=LessonPack.FAILED,
                                          created_at__lt=now - timedelta(days=FAILED_DAYS)).delete()
    # Only drafts that were never published: a lesson that got new material is a draft again, and
    # deleting it would delete everyone's progress on its old cards.
    drafts, _ = LessonPack.objects.filter(status__in=[LessonPack.DRAFT, LessonPack.EMPTY], published_at__isnull=True,
                                          created_at__lt=now - timedelta(days=DRAFT_DAYS)).delete()
    PendingUpload.objects.filter(pack__status=LessonPack.FAILED).delete()   # files of failed builds are not kept
    counts = {'stuck': stuck, 'deleted': failed + drafts}
    if stuck or failed or drafts:
        logger.info('LearningJourney cleanup: %s', counts)
    return counts


def maybe_run():
    """Called by the idle worker every few minutes; runs at most once an hour."""
    global _last_check
    if _last_check is not None and time.monotonic() - _last_check < CHECK_EVERY:
        return None
    _last_check = time.monotonic()
    return run()
