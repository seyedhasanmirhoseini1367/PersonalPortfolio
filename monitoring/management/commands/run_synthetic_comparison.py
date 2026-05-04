"""
Management command: run synthetic EEG inference across all three seizure models
and log per-model + ensemble results for side-by-side comparison in monitoring.

Usage:
    python manage.py run_synthetic_comparison
    python manage.py run_synthetic_comparison --samples 10
    python manage.py run_synthetic_comparison --triggered-by manual

Reads the same SYNTHETIC_DATA_DIR / SYNTHETIC_TARGET_CSV settings as the
single-model monitor.  Finds every project whose file_input_config.handler
== "seizure_eeg" automatically, so adding a fourth model requires no code
changes.

Each file produces one PredictionLog per model (source='synthetic_comparison')
storing the comparison_run_id in input_data so the comparison view can
reconstruct the per-run table.  One MonitorRun is also written per project.
"""

import io
import random
import time
import uuid
import logging
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils import timezone

import pandas as pd

logger = logging.getLogger(__name__)

_COMPARABLE_LABELS = {'LPD', 'Seizure'}


def _normalize(label: str) -> str:
    if label.upper().startswith('LPD'):
        return 'LPD'
    if label.strip().lower() == 'seizure':
        return 'Seizure'
    return label.strip()


class Command(BaseCommand):
    help = 'Synthetic comparison run across all seizure EEG models'

    def add_arguments(self, parser):
        parser.add_argument('--samples', type=int, default=None,
                            help='Fixed number of samples (default: random within MIN/MAX_SAMPLES)')
        parser.add_argument('--triggered-by', default='scheduler',
                            choices=['scheduler', 'manual'])

    def handle(self, *args, **options):
        cfg        = getattr(settings, 'SYNTHETIC_MONITOR', {})
        data_dir   = cfg.get('DATA_DIR', '')
        target_csv = cfg.get('TARGET_CSV', '')
        min_s      = cfg.get('MIN_SAMPLES', 5)
        max_s      = cfg.get('MAX_SAMPLES', 15)
        triggered  = options.get('triggered_by', 'scheduler')

        if not data_dir or not Path(data_dir).exists():
            self.stderr.write(self.style.ERROR(
                f'Data directory not found: "{data_dir}"\n'
                'Set SYNTHETIC_DATA_DIR in your .env file.'
            ))
            return

        # ── Find all seizure EEG projects ─────────────────────────────────────
        from projects.models import Projects
        from projects.inference import get_handler
        from monitoring.models import PredictionLog, MonitorRun

        seizure_projects = [
            p for p in Projects.objects.filter(is_public=True)
            if (p.file_input_config or {}).get('handler') == 'seizure_eeg'
        ]
        if not seizure_projects:
            self.stderr.write(self.style.ERROR(
                'No public projects with file_input_config.handler="seizure_eeg" found.'
            ))
            return

        self.stdout.write(
            f'Models ({len(seizure_projects)}): '
            + ', '.join(
                f'{p.title} [{(p.file_input_config or {}).get("model_variant","?")}]'
                for p in seizure_projects
            )
        )

        # ── Load ground-truth labels ──────────────────────────────────────────
        targets: dict = {}
        if target_csv and Path(target_csv).exists():
            try:
                df_t    = pd.read_csv(target_csv, dtype={'eeg_id': str})
                targets = dict(zip(df_t['eeg_id'].astype(str), df_t['target']))
                self.stdout.write(f'Loaded {len(targets)} ground-truth labels')
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'Could not load targets: {exc}'))

        # ── Sample files ──────────────────────────────────────────────────────
        parquet_files = list(Path(data_dir).glob('*.parquet'))
        if not parquet_files:
            self.stderr.write(self.style.ERROR(f'No .parquet files in {data_dir}'))
            return

        n        = options['samples'] or random.randint(min_s, max_s)
        n        = min(n, len(parquet_files))
        selected = random.sample(parquet_files, n)

        run_id      = uuid.uuid4().hex[:10]
        run_started = timezone.now()

        self.stdout.write(f'\nComparison run {run_id} — {n} samples\n' + '─' * 72)

        # Per-project accumulators
        stats = {
            p.id: {'ok': 0, 'fail': 0, 'correct': 0, 'comparable': 0,
                   'latencies': [], 'confidences': []}
            for p in seizure_projects
        }
        ens_correct = ens_comparable = 0

        for file_path in selected:
            eeg_id       = file_path.stem
            expected_raw = targets.get(eeg_id)
            can_compare  = expected_raw in _COMPARABLE_LABELS
            raw_bytes    = file_path.read_bytes()

            model_results = []  # list of dicts

            for project in seizure_projects:
                variant  = (project.file_input_config or {}).get('model_variant', '?')
                file_obj = InMemoryUploadedFile(
                    file         = io.BytesIO(raw_bytes),
                    field_name   = 'file',
                    name         = file_path.name,
                    content_type = 'application/octet-stream',
                    size         = len(raw_bytes),
                    charset      = None,
                )
                try:
                    handler    = get_handler(project)
                    t0         = time.monotonic()
                    result     = handler.run(file_obj)
                    ms         = int((time.monotonic() - t0) * 1000)
                    pred_label = result.get('prediction_label', '')
                    confidence = result.get('prediction_proba') or result.get('confidence')
                    norm_label = _normalize(pred_label)
                    is_correct = (norm_label == expected_raw) if can_compare else None

                    model_results.append({
                        'project':   project,
                        'variant':   variant,
                        'label':     pred_label,
                        'norm':      norm_label,
                        'confidence': confidence,
                        'prediction': result.get('prediction'),
                        'ms':        ms,
                        'success':   True,
                        'is_correct': is_correct,
                    })

                    s = stats[project.id]
                    s['ok'] += 1
                    s['latencies'].append(ms)
                    if confidence is not None:
                        s['confidences'].append(confidence)
                    if can_compare:
                        s['comparable'] += 1
                        if is_correct:
                            s['correct'] += 1

                except Exception as exc:
                    model_results.append({
                        'project':  project,
                        'variant':  variant,
                        'label':    '',
                        'norm':     '',
                        'success':  False,
                        'error':    str(exc),
                    })
                    stats[project.id]['fail'] += 1
                    self.stdout.write(
                        self.style.ERROR(f'  {eeg_id} [{variant}] FAILED: {exc}')
                    )

            # ── Ensemble vote ─────────────────────────────────────────────────
            valid_norms    = [r['norm'] for r in model_results if r['success'] and r['norm']]
            ensemble_label = Counter(valid_norms).most_common(1)[0][0] if valid_norms else None
            all_agree      = len(set(valid_norms)) == 1 if valid_norms else False

            if can_compare and ensemble_label:
                ens_comparable += 1
                if ensemble_label == expected_raw:
                    ens_correct += 1

            # ── Persist one PredictionLog per model ───────────────────────────
            for r in model_results:
                log_kwargs = dict(
                    project    = r['project'],
                    user       = None,
                    input_type = 'file',
                    source     = 'synthetic_comparison',
                    input_data = {
                        'eeg_id':           eeg_id,
                        'expected_label':   expected_raw or 'unknown',
                        'is_correct':       r.get('is_correct'),
                        'comparable':       can_compare,
                        'model_variant':    r['variant'],
                        'comparison_run_id': run_id,
                        'ensemble_label':   ensemble_label,
                        'all_agree':        all_agree,
                    },
                )
                if r['success']:
                    log_kwargs.update(
                        prediction   = r.get('prediction'),
                        confidence   = r.get('confidence'),
                        label        = r['label'],
                        inference_ms = r['ms'],
                        success      = True,
                    )
                else:
                    log_kwargs.update(
                        prediction    = None,
                        confidence    = None,
                        label         = '',
                        inference_ms  = None,
                        success       = False,
                        error_message = r.get('error', ''),
                    )
                PredictionLog.objects.create(**log_kwargs)

            # ── Console line ──────────────────────────────────────────────────
            preds_str = '  '.join(
                f'[{r["variant"]}] {"✓" if r.get("is_correct") else ("✗" if r.get("is_correct") is False else "?") if r["success"] else "ERR"}'
                f' {r["norm"] or r.get("error","")}'
                for r in model_results
            )
            ens_str = f'→ ENS: {ensemble_label or "—"}'
            if can_compare and ensemble_label:
                ens_str += f' {"✓" if ensemble_label == expected_raw else "✗"}'
            self.stdout.write(f'  {eeg_id:<14} {preds_str}  {ens_str}')

        # ── MonitorRun per project ────────────────────────────────────────────
        now = timezone.now()
        for project in seizure_projects:
            s = stats[project.id]
            MonitorRun.objects.create(
                project        = project,
                started_at     = run_started,
                completed_at   = now,
                triggered_by   = triggered,
                n_samples      = s['ok'] + s['fail'],
                n_success      = s['ok'],
                n_failed       = s['fail'],
                n_comparable   = s['comparable'],
                n_correct      = s['correct'],
                avg_latency_ms = (sum(s['latencies']) / len(s['latencies'])
                                  if s['latencies'] else None),
                avg_confidence = (sum(s['confidences']) / len(s['confidences'])
                                  if s['confidences'] else None),
            )

        # ── Final summary ─────────────────────────────────────────────────────
        self.stdout.write('─' * 72)
        for project in seizure_projects:
            s       = stats[project.id]
            variant = (project.file_input_config or {}).get('model_variant', '?')
            acc     = (f'{s["correct"]}/{s["comparable"]} '
                       f'({100*s["correct"]//s["comparable"]}%)'
                       if s['comparable'] else '—')
            self.stdout.write(
                f'  {variant:<18} {project.title:<38} acc={acc}  '
                f'ok={s["ok"]} fail={s["fail"]}'
            )
        ens_acc = (f'{ens_correct}/{ens_comparable} '
                   f'({100*ens_correct//ens_comparable}%)'
                   if ens_comparable else '—')
        self.stdout.write(self.style.SUCCESS(
            f'  {"ensemble":<18} {"(majority vote)":<38} acc={ens_acc}'
        ))
        self.stdout.write(self.style.SUCCESS(f'\nRun {run_id} complete.'))
