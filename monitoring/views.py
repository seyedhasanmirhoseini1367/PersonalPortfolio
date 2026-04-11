from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Avg, Q
from django.db.models.functions import TruncDate, TruncHour
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
import json

from .models import PredictionLog
from projects.models import Projects


@staff_member_required
def dashboard(request):
    """Main monitoring dashboard — staff only."""
    days = int(request.GET.get('days', 7))
    since = timezone.now() - timedelta(days=days)

    projects = Projects.objects.filter(is_public=True, prediction_endpoint=True)
    project_id = request.GET.get('project')
    selected_project = None

    logs = PredictionLog.objects.filter(created_at__gte=since)
    if project_id:
        logs = logs.filter(project_id=project_id)
        try:
            selected_project = Projects.objects.get(pk=project_id)
        except Projects.DoesNotExist:
            pass

    # ── Summary stats ──────────────────────────────────────────────────────────
    total       = logs.count()
    successful  = logs.filter(success=True).count()
    failed      = logs.filter(success=False).count()
    success_rate = round(successful / total * 100, 1) if total else 0
    avg_latency = logs.filter(success=True).aggregate(v=Avg('inference_ms'))['v']
    avg_conf    = logs.filter(success=True).aggregate(v=Avg('confidence'))['v']

    # ── Requests per day (chart) ───────────────────────────────────────────────
    daily = (
        logs.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'), errors=Count('id', filter=Q(success=False)))
            .order_by('day')
    )
    chart_labels = [str(r['day']) for r in daily]
    chart_counts = [r['count'] for r in daily]
    chart_errors = [r['errors'] for r in daily]

    # ── Per-model breakdown ────────────────────────────────────────────────────
    model_stats = (
        logs.values('project__id', 'project__title')
            .annotate(
                total=Count('id'),
                errors=Count('id', filter=Q(success=False)),
                avg_ms=Avg('inference_ms'),
                avg_conf=Avg('confidence'),
            )
            .order_by('-total')
    )

    # ── Latest 20 predictions ──────────────────────────────────────────────────
    recent = logs.select_related('project', 'user')[:20]

    # ── Source breakdown ───────────────────────────────────────────────────────
    sources = logs.values('source').annotate(count=Count('id')).order_by('-count')

    return render(request, 'monitoring/dashboard.html', {
        'projects':         projects,
        'selected_project': selected_project,
        'days':             days,
        'time_ranges':      [(1, '24h'), (7, '7d'), (30, '30d')],
        'total':            total,
        'successful':       successful,
        'failed':           failed,
        'success_rate':     success_rate,
        'avg_latency':      round(avg_latency, 1) if avg_latency else None,
        'avg_conf':         round(avg_conf * 100, 1) if avg_conf else None,
        'chart_labels':     json.dumps(chart_labels),
        'chart_counts':     json.dumps(chart_counts),
        'chart_errors':     json.dumps(chart_errors),
        'model_stats':      model_stats,
        'recent':           recent,
        'sources':          sources,
    })


@staff_member_required
def api_stats(request):
    """JSON endpoint for live refresh of stats."""
    since = timezone.now() - timedelta(hours=24)
    logs  = PredictionLog.objects.filter(created_at__gte=since)

    hourly = (
        logs.annotate(hour=TruncHour('created_at'))
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
    )

    return JsonResponse({
        'last_24h_total':   logs.count(),
        'last_24h_errors':  logs.filter(success=False).count(),
        'avg_latency_ms':   logs.aggregate(v=Avg('inference_ms'))['v'],
        'hourly': [{'hour': str(r['hour']), 'count': r['count']} for r in hourly],
    })


@staff_member_required
def storage_debug(request):
    """Temporary debug view — shows storage config on Azure."""
    import os
    from pathlib import Path
    from django.conf import settings
    from django.core.files.storage import default_storage

    media_root = Path(settings.MEDIA_ROOT)
    home_exists = Path('/home').exists()
    home_media_exists = Path('/home/media').exists()

    files = []
    if media_root.exists():
        for f in media_root.rglob('*'):
            if f.is_file():
                files.append(str(f))

    return JsonResponse({
        'MEDIA_ROOT':          str(settings.MEDIA_ROOT),
        'MEDIA_URL':           settings.MEDIA_URL,
        'storage_backend':     type(default_storage).__name__,
        'DEFAULT_FILE_STORAGE': getattr(settings, 'DEFAULT_FILE_STORAGE', 'not set'),
        '/home exists':        home_exists,
        '/home/media exists':  home_media_exists,
        'media_root_exists':   media_root.exists(),
        'files_in_media_root': files[:20],
        'WEBSITES_ENABLE_APP_SERVICE_STORAGE': os.environ.get('WEBSITES_ENABLE_APP_SERVICE_STORAGE', 'not set'),
    })
