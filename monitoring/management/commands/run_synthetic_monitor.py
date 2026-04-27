"""
Management command: run hourly synthetic EEG inference for model monitoring.

Picks 5–15 random parquet files from the test dataset, runs inference through
the SeizureEEGHandler, compares predictions against known labels where
available, and logs every result to PredictionLog (source='synthetic').

Schedule locally (Windows Task Scheduler):
    Action: python manage.py run_synthetic_monitor
    Trigger: Daily, repeat every 1 hour

Schedule on Azure (WebJob):
    App_Data/jobs/triggered/synthetic-monitor/run.cmd
    python manage.py run_synthetic_monitor
    Set CRON_SETTINGS in Azure Portal: 0 * * * * *

Required .env variables:
    SYNTHETIC_DATA_DIR=D:\Thesis\hms-harmful-brain-activity-classification/test_data
    SYNTHETIC_TARGET_CSV=D:\Thesis\hms-harmful-brain-activity-classification/target.csv
"""

import io
import random
import time
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils import timezone

import pandas as pd

logger = logging.getLogger(__name__)

# Labels the binary model can classify — only compute accuracy for these.
# HMS dataset has 6 classes; the model only distinguishes LPD vs Seizure.
_COMPARABLE_LABELS = {'LPD', 'Seizure'}


def _normalize_predicted(label: str) -> str:
    """Map verbose model label → simple form matching target.csv values."""
    if label.upper().startswith('LPD'):
        return 'LPD'
    if label.strip().lower() == 'seizure':
        return 'Seizure'
    return label.strip()


class Command(BaseCommand):
    help = 'Run synthetic EEG inference for hourly model health monitoring'

    def add_arguments(self, parser):
        parser.add_argument(
            '--samples', type=int, default=None,
            help='Fixed number of samples (default: random 5–15)',
        )
        parser.add_argument(
            '--triggered-by', default='scheduler',
            choices=['scheduler', 'manual'],
            help='Who triggered this run (used in MonitorRun record)',
        )

    def handle(self, *args, **options):
        cfg           = getattr(settings, 'SYNTHETIC_MONITOR', {})
        data_dir      = cfg.get('DATA_DIR', '')
        target_csv    = cfg.get('TARGET_CSV', '')
        project_title = cfg.get('PROJECT_TITLE', 'Seizure Detection')
        min_s         = cfg.get('MIN_SAMPLES', 5)
        max_s         = cfg.get('MAX_SAMPLES', 15)

        # ── Validate data directory ───────────────────────────────────────────
        if not data_dir or not Path(data_dir).exists():
            self.stderr.write(self.style.ERROR(
                f'Test data directory not found: "{data_dir}"\n'
                'Set SYNTHETIC_DATA_DIR=<path> in your .env file.'
            ))
            return

        # ── Load project ──────────────────────────────────────────────────────
        from projects.models import Projects
        try:
            project = Projects.objects.get(title=project_title)
        except Projects.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                f'Project "{project_title}" not found in database.'
            ))
            return

        # ── Load inference handler ────────────────────────────────────────────
        from projects.inference import get_handler
        try:
            handler = get_handler(project)
        except ValueError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        # ── Load targets (optional — graceful if missing) ─────────────────────
        targets: dict = {}
        if target_csv and Path(target_csv).exists():
            try:
                df_t = pd.read_csv(target_csv, dtype={'eeg_id': str})
                targets = dict(zip(df_t['eeg_id'].astype(str), df_t['target']))
                self.stdout.write(f'Loaded {len(targets)} labels from target.csv')
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'Could not load targets: {exc}'))

        # ── Scan test_data directory → pick from files, not from CSV ─────────
        parquet_files = list(Path(data_dir).glob('*.parquet'))
        if not parquet_files:
            self.stderr.write(self.style.ERROR(
                f'No .parquet files found in {data_dir}'
            ))
            return

        n = options['samples'] or random.randint(min_s, max_s)
        n = min(n, len(parquet_files))
        selected = random.sample(parquet_files, n)

        self.stdout.write(
            f'\nSynthetic monitor — {n} samples '
            f'(pool: {len(parquet_files)} files, '
            f'{len(targets)} with known labels)\n'
            + '-' * 60
        )

        # ── Run inference ─────────────────────────────────────────────────────
        from monitoring.models import PredictionLog, MonitorRun

        ok = fail = correct = comparable = 0
        latencies: list[float] = []
        confidences: list[float] = []
        run_started = timezone.now()

        for file_path in selected:
            eeg_id       = file_path.stem          # "51360893"
            expected_raw = targets.get(eeg_id)     # "LPD" / "Seizure" / None
            can_compare  = expected_raw in _COMPARABLE_LABELS
            is_correct   = None

            try:
                raw_bytes = file_path.read_bytes()
                file_obj  = InMemoryUploadedFile(
                    file         = io.BytesIO(raw_bytes),
                    field_name   = 'file',
                    name         = file_path.name,
                    content_type = 'application/octet-stream',
                    size         = len(raw_bytes),
                    charset      = None,
                )

                t0           = time.monotonic()
                result       = handler.run(file_obj)
                inference_ms = int((time.monotonic() - t0) * 1000)

                pred_label  = result.get('prediction_label', '')
                confidence  = result.get('prediction_proba') or result.get('confidence')

                if can_compare:
                    is_correct = _normalize_predicted(pred_label) == expected_raw
                    comparable += 1
                    if is_correct:
                        correct += 1

                PredictionLog.objects.create(
                    project      = project,
                    user         = None,
                    input_data   = {
                        'eeg_id':         eeg_id,
                        'expected_label': expected_raw or 'unknown',
                        'is_correct':     is_correct,
                        'comparable':     can_compare,
                    },
                    input_type   = 'file',
                    prediction   = result.get('prediction'),
                    confidence   = confidence,
                    label        = pred_label,
                    inference_ms = inference_ms,
                    success      = True,
                    source       = 'synthetic',
                )

                verdict = ''
                if can_compare:
                    verdict = f'  ✓' if is_correct else f'  ✗ (expected {expected_raw})'
                elif expected_raw:
                    verdict = f'  — ({expected_raw}, not comparable)'

                self.stdout.write(
                    f'  {eeg_id:<15} → {pred_label:<35} '
                    f'{confidence:.1%}  {inference_ms}ms{verdict}'
                )
                latencies.append(inference_ms)
                if confidence is not None:
                    confidences.append(confidence)
                ok += 1

            except Exception as exc:
                PredictionLog.objects.create(
                    project       = project,
                    user          = None,
                    input_data    = {
                        'eeg_id':         eeg_id,
                        'expected_label': expected_raw or 'unknown',
                    },
                    input_type    = 'file',
                    prediction    = None,
                    confidence    = None,
                    label         = '',
                    inference_ms  = None,
                    success       = False,
                    error_message = str(exc),
                    source        = 'synthetic',
                )
                self.stdout.write(self.style.ERROR(f'  {eeg_id:<15} FAILED: {exc}'))
                fail += 1

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('-' * 60)
        acc_str = (
            f' | Accuracy: {correct}/{comparable} '
            f'({correct/comparable*100:.0f}%)'
            if comparable else ''
        )
        style = self.style.SUCCESS if fail == 0 else self.style.WARNING
        self.stdout.write(style(
            f'Done: {ok} OK, {fail} failed{acc_str}'
        ))

        # ── Persist run-level aggregate ───────────────────────────────────────
        MonitorRun.objects.create(
            project        = project,
            started_at     = run_started,
            completed_at   = timezone.now(),
            triggered_by   = options.get('triggered_by', 'scheduler'),
            n_samples      = ok + fail,
            n_success      = ok,
            n_failed       = fail,
            n_comparable   = comparable,
            n_correct      = correct,
            avg_latency_ms = sum(latencies) / len(latencies) if latencies else None,
            avg_confidence = sum(confidences) / len(confidences) if confidences else None,
        )
