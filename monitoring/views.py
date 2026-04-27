from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Avg, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
import json

from .models import PredictionLog, MonitorRun
from projects.models import Projects


@staff_member_required
def dashboard(request):
    """Professional MLOps monitoring dashboard — staff only."""
    days       = int(request.GET.get('days', 7))
    since      = timezone.now() - timedelta(days=days)
    project_id = request.GET.get('project') or None

    projects = Projects.objects.filter(is_public=True, prediction_endpoint=True)
    selected_project = None
    if project_id:
        try:
            selected_project = Projects.objects.get(pk=project_id)
        except Projects.DoesNotExist:
            project_id = None

    # ── Base querysets ────────────────────────────────────────────────────────
    period_qs = PredictionLog.objects.filter(created_at__gte=since)
    if project_id:
        period_qs = period_qs.filter(project_id=project_id)

    real_qs = period_qs.exclude(source='synthetic')
    syn_qs  = period_qs.filter(source='synthetic')

    # ── All-time run aggregates (MonitorRun, not time-windowed) ───────────────
    run_qs = MonitorRun.objects.all()
    if project_id:
        run_qs = run_qs.filter(project_id=project_id)

    run_totals = run_qs.aggregate(
        total_comparable=Sum('n_comparable'),
        total_correct=Sum('n_correct'),
        total_runs=Count('id'),
        total_syn_samples=Sum('n_samples'),
    )
    all_comparable  = run_totals['total_comparable'] or 0
    all_correct     = run_totals['total_correct'] or 0
    total_runs      = run_totals['total_runs'] or 0
    syn_accuracy    = round(all_correct / all_comparable * 100, 1) if all_comparable else None

    # ── Combined KPI stats (real + synthetic) ────────────────────────────────
    all_total    = period_qs.count()
    all_failed   = period_qs.filter(success=False).count()
    all_error_rt = round(all_failed / all_total * 100, 1) if all_total else 0

    # P50 / P95 latency from all predictions in window
    lat_values = sorted(
        period_qs.filter(success=True, inference_ms__isnull=False)
                 .values_list('inference_ms', flat=True)
    )
    p50_latency = lat_values[len(lat_values) // 2] if lat_values else None
    p95_latency = lat_values[min(int(len(lat_values) * 0.95), len(lat_values) - 1)] \
                  if lat_values else None

    avg_conf_all = period_qs.filter(success=True).aggregate(v=Avg('confidence'))['v']

    # ── Volume by day (combined — used for bar chart) ─────────────────────────
    daily = (
        period_qs
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'), errors=Count('id', filter=Q(success=False)))
        .order_by('day')
    )
    chart_labels = json.dumps([str(r['day']) for r in daily])
    chart_counts = json.dumps([r['total'] for r in daily])
    chart_errors = json.dumps([r['errors'] for r in daily])

    # ── Label distribution ────────────────────────────────────────────────────
    label_dist = list(
        period_qs.exclude(label='')
                 .values('label')
                 .annotate(count=Count('id'))
                 .order_by('-count')[:8]
    )
    label_dist_json = json.dumps({r['label']: r['count'] for r in label_dist})

    # ── Trend chart data (last 20 comparable MonitorRuns, chronological) ──────
    trend_qs_q = list(reversed(
        run_qs.filter(n_comparable__gt=0).order_by('-started_at')[:20]
    ))
    trend_labels   = json.dumps([r.started_at.strftime('%m/%d %H:%M') for r in trend_qs_q])
    trend_accuracy = json.dumps([
        round(r.n_correct / r.n_comparable * 100, 1) for r in trend_qs_q
    ])
    trend_latency  = json.dumps([
        round(r.avg_latency_ms, 1) if r.avg_latency_ms else None for r in trend_qs_q
    ])

    # ── Model health status ───────────────────────────────────────────────────
    last_run = run_qs.order_by('-started_at').first()
    if last_run:
        cfg      = getattr(__import__('django.conf', fromlist=['settings']).settings,
                           'SYNTHETIC_MONITOR', {})
        interval = cfg.get('INTERVAL_MINUTES', 30)
        mins_ago = (timezone.now() - last_run.started_at).total_seconds() / 60
        acc      = last_run.accuracy  # property — None if no comparable
        if mins_ago <= interval * 2.5 and last_run.n_failed == 0 and (acc is None or acc >= 60):
            model_status = 'healthy'
        elif mins_ago <= interval * 5:
            model_status = 'warning'
        else:
            model_status = 'stale'
    else:
        model_status = 'unknown'

    # ── Merged recent predictions table (real + synthetic, latest 200) ────────
    combined_recent = (
        period_qs.select_related('project', 'user').order_by('-created_at')[:200]
    )

    # ── Per-model breakdown (real traffic) ────────────────────────────────────
    model_stats = (
        real_qs.values('project__id', 'project__title')
               .annotate(
                   total=Count('id'),
                   errors=Count('id', filter=Q(success=False)),
                   avg_ms=Avg('inference_ms'),
                   avg_conf=Avg('confidence'),
               ).order_by('-total')
    )

    # ── Run history (all-time, newest first) ──────────────────────────────────
    run_history = run_qs.select_related('project').order_by('-started_at')[:60]

    # ── Synthetic summary (for info card) ─────────────────────────────────────
    syn_total    = syn_qs.count()
    syn_avg_ms   = syn_qs.filter(success=True).aggregate(v=Avg('inference_ms'))['v']
    syn_avg_conf = syn_qs.filter(success=True).aggregate(v=Avg('confidence'))['v']

    return render(request, 'monitoring/dashboard.html', {
        'projects':         projects,
        'selected_project': selected_project,
        'days':             days,
        'time_ranges':      [(1, '24h'), (7, '7d'), (30, '30d')],
        # Health
        'model_status':     model_status,
        'last_run':         last_run,
        'total_runs':       total_runs,
        # Combined KPIs
        'all_total':        all_total,
        'all_failed':       all_failed,
        'all_error_rt':     all_error_rt,
        'p50_latency':      p50_latency,
        'p95_latency':      p95_latency,
        'avg_conf_all':     round(avg_conf_all * 100, 1) if avg_conf_all else None,
        'syn_accuracy':     syn_accuracy,
        'all_comparable':   all_comparable,
        # Charts
        'chart_labels':     chart_labels,
        'chart_counts':     chart_counts,
        'chart_errors':     chart_errors,
        'label_dist_json':  label_dist_json,
        'label_dist':       label_dist,
        'trend_labels':     trend_labels,
        'trend_accuracy':   trend_accuracy,
        'trend_latency':    trend_latency,
        # Tables
        'combined_recent':  combined_recent,
        'model_stats':      model_stats,
        'run_history':      run_history,
        # Synthetic summary
        'syn_total':        syn_total,
        'syn_avg_ms':       round(syn_avg_ms, 1) if syn_avg_ms else None,
        'syn_avg_conf':     round(syn_avg_conf * 100, 1) if syn_avg_conf else None,
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
