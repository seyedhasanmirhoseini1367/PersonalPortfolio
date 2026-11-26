"""Spaced repetition (SM-2, as used by Anki's original scheduler).

Grades: 0 = forgot, 3 = hard, 4 = good, 5 = easy.
"""
from datetime import timedelta

from django.utils import timezone

AGAIN, HARD, GOOD, EASY = 0, 3, 4, 5
GRADES = {'again': AGAIN, 'hard': HARD, 'good': GOOD, 'easy': EASY}

# A forgotten card comes back in the same session, after a short pause.
RELEARN_DELAY = timedelta(minutes=10)


def schedule(progress, grade, now=None):
    """Update a Progress row in place for one answer and return it (not saved)."""
    now = now or timezone.now()
    grade = max(0, min(5, int(grade)))
    if grade < 3:
        if progress.reps > 0:
            progress.lapses += 1
        progress.reps = 0
        progress.interval = 0
        progress.due = now + RELEARN_DELAY
    else:
        if progress.reps == 0:
            progress.interval = 1
        elif progress.reps == 1:
            progress.interval = 6 if grade >= GOOD else 3
        else:
            factor = progress.ease * (1.3 if grade == EASY else 1.0) * (0.8 if grade == HARD else 1.0)
            progress.interval = max(progress.interval + 1, round(progress.interval * factor))
        progress.reps += 1
        progress.due = now + timedelta(days=progress.interval)
    # SM-2 ease update, kept at 1.3 or more.
    progress.ease = max(1.3, progress.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    progress.last_reviewed = now
    return progress
