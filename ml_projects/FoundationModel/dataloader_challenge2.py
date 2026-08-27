import os
import glob
import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset
import mne
import warnings

warnings.filterwarnings('ignore')

from typing import List, Tuple, Optional

TASK_FLAG_COLS = {
    'RestingState':            ['RestingState'],
    'DespicableMe':            ['DespicableMe'],
    'FunwithFractals':         ['FunwithFractals'],
    'ThePresent':              ['ThePresent'],
    'DiaryOfAWimpyKid':        ['DiaryOfAWimpyKid'],
    'contrastChangeDetection': ['contrastChangeDetection_1', 'contrastChangeDetection_2', 'contrastChangeDetection_3'],
    'surroundSupp':            ['surroundSupp_1', 'surroundSupp_2'],
    'seqLearning8target':      ['seqLearning8target'],
    'seqLearning6target':      ['seqLearning6target'],
    'symbolSearch':            ['symbolSearch'],
}


def _subject_has_task(row: pd.Series, task: str) -> bool:
    cols = TASK_FLAG_COLS.get(task)
    if cols is None:
        return True
    return any(col in row.index and str(row[col]).strip().lower() == 'available' for col in cols)


class ExternalizingFineTuneDataset(Dataset):
    """
    Challenge 2: predict externalizing factor from windowed EEG.

    externalizing is a subject-level label read from participants.tsv.
    Multiple random windows are sampled per subject per task file so
    the model sees more signal diversity from each subject.
    """

    def __init__(
        self,
        root_dirs: List[str],
        window_length_s: float = 2.0,
        sfreq: int = 100,
        n_windows_per_subject: int = 20,
        tasks: Optional[List[str]] = None,
        normalization: str = 'zscore',
        transform=None,
    ):
        self.window_samples = int(window_length_s * sfreq)
        self.sfreq = sfreq
        self.n_windows_per_subject = n_windows_per_subject
        self.normalization = normalization
        self.transform = transform

        all_tasks = [
            'contrastChangeDetection', 'seqLearning8target', 'symbolSearch',
            'RestingState', 'surroundSupp', 'DespicableMe',
            'DiaryOfAWimpyKid', 'FunwithFractals', 'ThePresent',
        ]
        self.tasks = tasks if tasks is not None else all_tasks

        # Each entry: (eeg_tensor, externalizing, subject_id)
        self.windows: List[Tuple[torch.Tensor, float, str]] = []

        for root_dir in root_dirs:
            if not os.path.exists(root_dir):
                continue
            self._load_root(root_dir)

        print(f"ExternalizingFineTuneDataset: {len(self.windows)} windows across {len(root_dirs)} root dirs")

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_root(self, root_dir: str):
        participants_file = os.path.join(root_dir, 'participants.tsv')
        if not os.path.exists(participants_file):
            print(f"  Warning: no participants.tsv in {root_dir}")
            return

        participants = pd.read_csv(participants_file, sep='\t')
        if 'externalizing' not in participants.columns:
            print(f"  Warning: externalizing column missing in {participants_file}")
            return

        participants['participant_id'] = participants['participant_id'].astype(str)
        ext_map: dict  = dict(zip(participants['participant_id'], participants['externalizing']))
        row_map: dict  = {row['participant_id']: row for _, row in participants.iterrows()}

        for subject in [d for d in os.listdir(root_dir) if d.startswith('sub-')]:
            externalizing = ext_map.get(subject)
            if externalizing is None or (isinstance(externalizing, float) and np.isnan(externalizing)):
                continue

            eeg_dir = os.path.join(root_dir, subject, 'eeg')
            if not os.path.isdir(eeg_dir):
                continue

            row = row_map.get(subject)
            subject_files: List[str] = []
            for task in self.tasks:
                if row is not None and not _subject_has_task(row, task):
                    continue
                subject_files.extend(
                    glob.glob(os.path.join(eeg_dir, f"{subject}_task-{task}*eeg.bdf"))
                )

            if not subject_files:
                continue

            self.windows.extend(
                self._extract_windows(subject_files, float(externalizing), subject)
            )

    def _extract_windows(
        self, eeg_files: List[str], externalizing: float, subject_id: str
    ) -> List[Tuple[torch.Tensor, float, str]]:
        windows: List[Tuple[torch.Tensor, float, str]] = []
        windows_per_file = max(1, self.n_windows_per_subject // len(eeg_files))

        for eeg_file in eeg_files:
            try:
                raw = mne.io.read_raw_bdf(eeg_file, preload=True, verbose=False)
                if raw.info['sfreq'] != self.sfreq:
                    raw.resample(self.sfreq, verbose=False)
                data = raw.get_data()

                if np.isnan(data).any():
                    data = np.nan_to_num(data)

                if data.shape[1] < self.window_samples:
                    continue

                data = self._normalize(data)

                n_possible = data.shape[1] - self.window_samples
                starts = np.random.randint(0, n_possible, size=windows_per_file)
                for start in starts:
                    t = torch.tensor(
                        data[:, start:start + self.window_samples],
                        dtype=torch.float32,
                    )
                    windows.append((t, externalizing, subject_id))

            except Exception as exc:
                print(f"  Error loading {eeg_file}: {exc}")

        return windows

    def _normalize(self, data: np.ndarray) -> np.ndarray:
        if self.normalization == 'zscore':
            mean = np.mean(data, axis=1, keepdims=True)
            std  = np.std(data,  axis=1, keepdims=True)
            std  = np.where(std == 0, 1e-8, std)
            return (data - mean) / std
        if self.normalization == 'minmax':
            lo  = np.min(data, axis=1, keepdims=True)
            hi  = np.max(data, axis=1, keepdims=True)
            rng = np.where(hi - lo == 0, 1e-8, hi - lo)
            return 2 * (data - lo) / rng - 1
        return data

    # ── Dataset interface ─────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, idx: int) -> dict:
        eeg, externalizing, subject_id = self.windows[idx]
        if self.transform:
            eeg = self.transform(eeg)
        return {
            'eeg':           eeg,
            'externalizing': torch.tensor(externalizing, dtype=torch.float32),
            'subject_id':    subject_id,
        }


def externalizing_collate_fn(batch: list) -> dict:
    """Stack fixed-length windows into a padded batch."""
    return {
        'eeg':           torch.stack([item['eeg']           for item in batch]),
        'externalizing': torch.stack([item['externalizing'] for item in batch]),
        'subject_id':    [item['subject_id']                for item in batch],
    }
