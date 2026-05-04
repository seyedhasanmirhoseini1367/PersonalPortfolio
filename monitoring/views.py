from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Avg, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
import json
import statistics

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
    p99_latency = lat_values[min(int(len(lat_values) * 0.99), len(lat_values) - 1)] \
                  if lat_values else None

    avg_conf_all = period_qs.filter(success=True).aggregate(v=Avg('confidence'))['v']

    # ── Throughput ────────────────────────────────────────────────────────────
    throughput_per_hour = round(all_total / (days * 24), 1) if (days and all_total) else 0

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

    # ── Confusion matrix (all-time synthetic comparable) ─────────────────────
    conf_logs = PredictionLog.objects.filter(source='synthetic', input_data__comparable=True)
    if project_id:
        conf_logs = conf_logs.filter(project_id=project_id)

    tp = conf_logs.filter(label__iexact='Seizure',         input_data__expected_label='Seizure').count()
    fp = conf_logs.filter(label__iexact='Seizure',         input_data__expected_label='LPD').count()
    fn = conf_logs.exclude(label__iexact='Seizure').filter(input_data__expected_label='Seizure').count()
    tn = conf_logs.exclude(label__iexact='Seizure').filter(input_data__expected_label='LPD').count()

    precision_seizure = round(tp / (tp + fp) * 100, 1) if (tp + fp) else None
    recall_seizure    = round(tp / (tp + fn) * 100, 1) if (tp + fn) else None
    f1_seizure = round(
        2 * precision_seizure * recall_seizure / (precision_seizure + recall_seizure), 1
    ) if (precision_seizure and recall_seizure) else None
    fnr_seizure = round(fn / (fn + tp) * 100, 1) if (fn + tp) else None

    precision_lpd = round(tn / (tn + fn) * 100, 1) if (tn + fn) else None
    recall_lpd    = round(tn / (tn + fp) * 100, 1) if (tn + fp) else None
    f1_lpd = round(
        2 * precision_lpd * recall_lpd / (precision_lpd + recall_lpd), 1
    ) if (precision_lpd and recall_lpd) else None

    # ── Accuracy volatility across all comparable runs ────────────────────────
    run_acc_list = [r.accuracy for r in run_qs.filter(n_comparable__gt=0) if r.accuracy is not None]
    acc_std = round(statistics.stdev(run_acc_list), 1) if len(run_acc_list) >= 2 else None

    # ── Confidence calibration (10 bins, 0–10%, 10–20%, … 90–100%) ───────────
    calibration_data = []
    for i in range(10):
        low  = i / 10.0
        high = (i + 1) / 10.0 if i < 9 else 1.001
        bin_qs  = conf_logs.filter(confidence__gte=low, confidence__lt=high)
        n       = bin_qs.count()
        correct = bin_qs.filter(input_data__is_correct=True).count()
        calibration_data.append({
            'label':    f'{int(low*100)}-{int((i+1)*10)}',
            'expected': int((low + (i + 1) / 10) / 2 * 100),
            'actual':   round(correct / n * 100, 1) if n else None,
            'count':    n,
        })
    cal_labels   = json.dumps([b['label']    for b in calibration_data])
    cal_expected = json.dumps([b['expected'] for b in calibration_data])
    cal_actual   = json.dumps([b['actual']   for b in calibration_data])

    ece_num = ece_den = 0
    for b in calibration_data:
        if b['actual'] is not None and b['count']:
            ece_num += b['count'] * abs(b['expected'] - b['actual'])
            ece_den += b['count']
    ece = round(ece_num / ece_den, 1) if ece_den else None

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts = []
    if recall_seizure is not None and recall_seizure < 70:
        alerts.append({'level': 'critical',
                       'msg': f'Seizure Recall {recall_seizure}% — below 70% clinical threshold. Consider retraining.'})
    if fnr_seizure is not None and fnr_seizure > 10:
        alerts.append({'level': 'critical',
                       'msg': f'False Negative Rate {fnr_seizure}% — seizures are being missed.'})
    if acc_std is not None and acc_std > 15:
        alerts.append({'level': 'warning',
                       'msg': f'Accuracy volatility ±{acc_std}% std dev — model output is unstable across runs.'})
    if p95_latency and p95_latency > 200:
        alerts.append({'level': 'warning',
                       'msg': f'P95 latency {p95_latency}ms exceeds 200ms SLA threshold.'})
    if ece is not None and ece > 10:
        alerts.append({'level': 'warning',
                       'msg': f'Calibration Error ECE={ece}% — confidence scores are not well-calibrated.'})

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
        'p50_latency':           p50_latency,
        'p95_latency':           p95_latency,
        'p99_latency':           p99_latency,
        'throughput_per_hour':   throughput_per_hour,
        'avg_conf_all':          round(avg_conf_all * 100, 1) if avg_conf_all else None,
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
        # Confusion matrix & class metrics
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision_seizure': precision_seizure,
        'recall_seizure':    recall_seizure,
        'f1_seizure':        f1_seizure,
        'fnr_seizure':       fnr_seizure,
        'precision_lpd':     precision_lpd,
        'recall_lpd':        recall_lpd,
        'f1_lpd':            f1_lpd,
        # Stability
        'acc_std':           acc_std,
        # Calibration
        'cal_labels':        cal_labels,
        'cal_expected':      cal_expected,
        'cal_actual':        cal_actual,
        'ece':               ece,
        # Alerts
        'alerts':            alerts,
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
def comparison_view(request):
    """
    Side-by-side synthetic comparison dashboard.
    Shows per-model and ensemble accuracy for every run_synthetic_comparison run.
    """
    from collections import defaultdict

    # All comparison logs, newest first
    all_logs = (
        PredictionLog.objects
        .filter(source='synthetic_comparison')
        .order_by('-created_at')
        .select_related('project')
    )

    # ── Discover distinct runs ────────────────────────────────────────────────
    run_meta = {}   # run_id → {date, n_files, projects}
    for log in all_logs:
        rid = (log.input_data or {}).get('comparison_run_id')
        if not rid:
            continue
        if rid not in run_meta:
            run_meta[rid] = {'date': log.created_at, 'n_files': set(), 'project_ids': set()}
        run_meta[rid]['n_files'].add((log.input_data or {}).get('eeg_id', ''))
        run_meta[rid]['project_ids'].add(log.project_id)

    # Sort runs newest-first
    sorted_runs = sorted(run_meta.items(), key=lambda x: x[1]['date'], reverse=True)

    # ── Select active run ─────────────────────────────────────────────────────
    selected_run_id = request.GET.get('run') or (sorted_runs[0][0] if sorted_runs else None)

    run_logs = [l for l in all_logs if
                (l.input_data or {}).get('comparison_run_id') == selected_run_id]

    # ── Build model list (ordered by project id for stable column order) ──────
    seizure_projects = sorted(
        {l.project for l in run_logs},
        key=lambda p: p.id,
    )
    model_info = [
        {
            'project': p,
            'variant': (p.file_input_config or {}).get('model_variant', '?'),
            'title':   p.title,
        }
        for p in seizure_projects
    ]

    # ── Group logs by eeg_id ──────────────────────────────────────────────────
    by_eeg = defaultdict(dict)  # eeg_id → {variant: log}
    for log in run_logs:
        eeg_id  = (log.input_data or {}).get('eeg_id', '?')
        variant = (log.input_data or {}).get('model_variant', '?')
        by_eeg[eeg_id][variant] = log

    # ── Build row objects for template ────────────────────────────────────────
    rows = []
    ens_correct = ens_comparable = 0
    model_correct   = defaultdict(int)
    model_comparable = defaultdict(int)

    for eeg_id, variant_map in sorted(by_eeg.items()):
        # Read shared fields from any log
        any_log      = next(iter(variant_map.values()))
        expected     = (any_log.input_data or {}).get('expected_label', 'unknown')
        can_compare  = (any_log.input_data or {}).get('comparable', False)
        ensemble_lbl = (any_log.input_data or {}).get('ensemble_label')
        all_agree    = (any_log.input_data or {}).get('all_agree', False)

        cells = []
        valid_norms = []
        for mi in model_info:
            v   = mi['variant']
            log = variant_map.get(v)
            if log is None:
                cells.append({'label': '—', 'correct': None, 'confidence': None, 'ms': None, 'success': None})
                continue
            if not log.success:
                cells.append({'label': 'Error', 'correct': None, 'confidence': None, 'ms': None, 'success': False})
                continue

            norm    = log.label.upper().startswith('LPD') and 'LPD' or log.label.strip()
            correct = (log.input_data or {}).get('is_correct')
            cells.append({
                'label':      log.label,
                'correct':    correct,
                'confidence': round(log.confidence * 100, 1) if log.confidence else None,
                'ms':         log.inference_ms,
                'success':    True,
            })
            if can_compare and correct is not None:
                model_correct[v]    += int(bool(correct))
                model_comparable[v] += 1
            if log.label:
                valid_norms.append(log.label)

        ens_correct_row = None
        if can_compare and ensemble_lbl:
            ens_comparable += 1
            ens_correct_row = _norm_label(ensemble_lbl) == _norm_label(expected)
            if ens_correct_row:
                ens_correct += 1

        rows.append({
            'eeg_id':       eeg_id,
            'expected':     expected,
            'can_compare':  can_compare,
            'cells':        cells,
            'ensemble':     ensemble_lbl,
            'ens_correct':  ens_correct_row,
            'all_agree':    all_agree,
        })

    # ── Per-model summary cards ───────────────────────────────────────────────
    model_summaries = []
    for mi in model_info:
        v   = mi['variant']
        comp = model_comparable[v]
        corr = model_correct[v]
        model_summaries.append({
            'variant':    v,
            'title':      mi['title'],
            'comparable': comp,
            'correct':    corr,
            'accuracy':   round(100 * corr / comp, 1) if comp else None,
        })

    ens_accuracy = round(100 * ens_correct / ens_comparable, 1) if ens_comparable else None

    return render(request, 'monitoring/comparison.html', {
        'sorted_runs':     sorted_runs,
        'selected_run_id': selected_run_id,
        'model_info':      model_info,
        'model_summaries': model_summaries,
        'rows':            rows,
        'ens_correct':     ens_correct,
        'ens_comparable':  ens_comparable,
        'ens_accuracy':    ens_accuracy,
        'run_date':        run_meta[selected_run_id]['date'] if selected_run_id in run_meta else None,
    })


def _norm_label(label: str) -> str:
    if label.upper().startswith('LPD'):
        return 'LPD'
    return label.strip()


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
