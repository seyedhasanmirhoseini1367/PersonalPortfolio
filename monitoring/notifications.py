"""
Notification logic for model monitoring.

Two modes:
  1. Milestone alerts  — sent immediately when a model hits 10/50/100/500 predictions
  2. Daily digest      — summary email sent once per day via management command

Run the daily digest via cron:
    0 8 * * * cd /app && python manage.py send_monitoring_digest
"""
import logging
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

MILESTONES = [10, 50, 100, 500, 1000]


def check_milestone(project):
    """
    Called after each successful prediction.
    Sends a one-time email when total predictions hit a milestone.
    Never raises.
    """
    from .models import PredictionLog
    total = PredictionLog.objects.filter(project=project, success=True).count()

    if total not in MILESTONES:
        return

    _send(
        subject=f'🎉 {project.title} hit {total} predictions!',
        body=(
            f'Your model "{project.title}" has now been used {total} times.\n\n'
            f'Check the monitoring dashboard for full stats:\n'
            f'{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "localhost"}/monitoring/\n\n'
            f'— PersonalPortfolio'
        ),
    )


def send_daily_digest():
    """
    Send a daily summary of all model activity.
    Called by management command `send_monitoring_digest`.
    """
    from .models import PredictionLog
    from projects.models import Projects

    since = timezone.now() - timedelta(hours=24)
    logs  = PredictionLog.objects.filter(created_at__gte=since)

    if not logs.exists():
        return   # nothing to report

    total    = logs.count()
    errors   = logs.filter(success=False).count()
    from django.db.models import Avg
    avg_ms   = logs.aggregate(v=Avg('inference_ms'))['v']

    lines = [
        '📊 PersonalPortfolio — Daily Model Activity Digest',
        f'Period: last 24 hours  ({timezone.now().strftime("%Y-%m-%d %H:%M UTC")})',
        '',
        f'Total predictions : {total}',
        f'Errors            : {errors}',
        f'Success rate      : {round((total-errors)/total*100,1) if total else 0}%',
        f'Avg latency       : {round(avg_ms,1) if avg_ms else "—"}ms',
        '',
        '─── Per model ───',
    ]

    from django.db.models import Count, Q
    model_stats = (
        logs.values('project__title')
            .annotate(total=Count('id'), errors=Count('id', filter=Q(success=False)))
            .order_by('-total')
    )
    for m in model_stats:
        lines.append(f"  {m['project__title']}: {m['total']} calls, {m['errors']} errors")

    lines += ['', '— PersonalPortfolio Monitoring']

    _send(
        subject=f'📊 Daily Digest — {total} predictions today',
        body='\n'.join(lines),
    )


def _send(subject, body):
    """Send email to DEFAULT_FROM_EMAIL recipient. Silent on failure."""
    recipient = getattr(settings, 'MONITORING_ALERT_EMAIL',
                        getattr(settings, 'DEFAULT_FROM_EMAIL', ''))
    if not recipient:
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=True)
        logger.info(f'Monitoring email sent: {subject}')
    except Exception as exc:
        logger.warning(f'Monitoring email failed: {exc}')
