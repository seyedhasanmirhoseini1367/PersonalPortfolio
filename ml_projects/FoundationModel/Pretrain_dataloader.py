import os
import glob
import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
import mne  # for loading .set .bdf EEG files
import warnings

warnings.filterwarnings('ignore')

from typing import List, Tuple, Optional, Dict, Any

# Maps task name → participants.tsv flag columns (1 = subject has that run)
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
    """Return True if the subject completed at least one run of the given task."""
    cols = TASK_FLAG_COLS.get(task)
    if cols is None:
        return True  # unknown task — don't filter
    return any(col in row.index and str(row[col]).strip().lower() == 'available' for col in cols)


# ======================= EEG Pretrain Dataset ==========================
class EEGPretrainDataset(Dataset):
    """
    Dataset for pre-training foundation model
    - Loads full EEG signals from all tasks
    - No windowing, no targets needed
    - Returns only EEG data tensors for self-supervised learning
    """

    def __init__(self, root_dirs: List[str], tasks: Optional[List[str]] = None, transform=None,
                 normalization: str = 'zscore', window_length_s: float = 4.0, sfreq: int = 100):
        self.transform = transform
        self.eeg_files = []
        self.tasks = tasks
        self.normalization = normalization
        self.window_samples = int(window_length_s * sfreq)
        self.sfreq = sfreq

        all_tasks = [
            'contrastChangeDetection', 'seqLearning8target', 'symbolSearch',
            'RestingState', 'surroundSupp', 'DespicableMe',
            'DiaryOfAWimpyKid', 'FunwithFractals', 'ThePresent'
        ]

        if tasks is None:
            self.tasks = all_tasks

        for root_dir in root_dirs:
            if not os.path.exists(root_dir):
                continue

            participants_file = os.path.join(root_dir, 'participants.tsv')
            if os.path.exists(participants_file):
                participants_df = pd.read_csv(participants_file, sep='\t')
                avail_map = {row['participant_id']: row for _, row in participants_df.iterrows()}
            else:
                avail_map = {}

            subjects = [sub for sub in os.listdir(root_dir) if sub.startswith('sub-')]
            for subject in subjects:
                task_path = os.path.join(root_dir, subject, 'eeg')
                if not os.path.exists(task_path):
                    continue

                row = avail_map.get(subject)
                for task in self.tasks:
                    if row is not None and not _subject_has_task(row, task):
                        continue
                    pattern = f"{subject}_task-{task}*eeg.bdf"
                    self.eeg_files.extend(glob.glob(os.path.join(task_path, pattern)))

        print(f"Found {len(self.eeg_files)} EEG files for pre-training")
        print(f"Using normalization: {normalization}")

    def _normalize_eeg(self, data: np.ndarray) -> np.ndarray:
        """Apply normalization to EEG data"""
        if self.normalization is None:
            return data

        if self.normalization == 'zscore':
            # Z-score normalization per channel
            mean = np.mean(data, axis=1, keepdims=True)
            std = np.std(data, axis=1, keepdims=True)
            std = np.where(std == 0, 1e-8, std)  # Avoid division by zero
            return (data - mean) / std

        elif self.normalization == 'minmax':
            # Min-max normalization per channel to [-1, 1]
            min_vals = np.min(data, axis=1, keepdims=True)
            max_vals = np.max(data, axis=1, keepdims=True)
            range_vals = max_vals - min_vals
            range_vals = np.where(range_vals == 0, 1e-8, range_vals)  # Avoid division by zero
            return 2 * (data - min_vals) / range_vals - 1

        else:
            return data

    def __len__(self):
        return len(self.eeg_files)

    def __getitem__(self, idx):
        eeg_path = self.eeg_files[idx]

        try:
            raw = mne.io.read_raw_bdf(eeg_path, preload=True, verbose=False)
            if raw.info['sfreq'] != self.sfreq:
                raw.resample(self.sfreq, verbose=False)
            data = raw.get_data()

            if np.isnan(data).any():
                data = np.nan_to_num(data)

            # Extract a random fixed-length window
            if data.shape[1] < self.window_samples:
                # recording shorter than window — pad with zeros
                pad = np.zeros((data.shape[0], self.window_samples - data.shape[1]))
                data = np.concatenate([data, pad], axis=1)
            else:
                start = np.random.randint(0, data.shape[1] - self.window_samples)
                data = data[:, start:start + self.window_samples]

            data = self._normalize_eeg(data)
            eeg_tensor = torch.tensor(data, dtype=torch.float32)

            if self.transform:
                eeg_tensor = self.transform(eeg_tensor)

            return eeg_tensor

        except Exception as e:
            print(f"Error loading {eeg_path}: {e}")
            return torch.zeros(129, self.window_samples)


def pretrain_collate_fn(batch):
    """Collate fixed-length windows — no padding needed."""
    return torch.stack(batch)


# ======================= EEG Pretrain Dataset By Subject ==========================

class EEGPretrainDatasetBySubject(Dataset):
    """
    Dataset organized by subject - returns ALL EEG files for each subject
    Each __getitem__ returns a list of tensors for one subject
    """

    def __init__(self, root_dirs: List[str], tasks: Optional[List[str]] = None, transform=None,
                 normalization: str = 'zscore'):
        self.transform = transform
        self.subjects_data = {}  # {subject_id: list_of_file_paths}
        self.normalization = normalization  # 'zscore', 'minmax', or None

        all_tasks = [
            'contrastChangeDetection', 'seqLearning8target', 'symbolSearch',
            'RestingState', 'surroundSupp', 'DespicableMe',
            'DiaryOfAWimpyKid', 'FunwithFractals', 'ThePresent'
        ]

        if tasks is None:
            tasks = all_tasks

        # Organize files by subject
        for root_dir in root_dirs:
            if not os.path.exists(root_dir):
                continue

            participants_file = os.path.join(root_dir, 'participants.tsv')
            if os.path.exists(participants_file):
                participants_df = pd.read_csv(participants_file, sep='\t')
                avail_map = {row['participant_id']: row for _, row in participants_df.iterrows()}
            else:
                avail_map = {}

            subjects = [sub for sub in os.listdir(root_dir) if sub.startswith('sub-')]
            for subject in subjects:
                task_path = os.path.join(root_dir, subject, 'eeg')
                if not os.path.exists(task_path):
                    continue

                row = avail_map.get(subject)
                subject_files = []
                for task in tasks:
                    if row is not None and not _subject_has_task(row, task):
                        continue
                    pattern = f"{subject}_task-{task}*eeg.bdf"
                    subject_files.extend(glob.glob(os.path.join(task_path, pattern)))

                if subject_files:
                    self.subjects_data[subject] = subject_files

        self.subject_ids = list(self.subjects_data.keys())
        print(f"Found {len(self.subject_ids)} subjects with EEG data")
        print(f"Using normalization: {normalization}")

    def _normalize_eeg(self, data: np.ndarray) -> np.ndarray:
        """Apply normalization to EEG data"""
        if self.normalization is None:
            return data

        if self.normalization == 'zscore':
            # Z-score normalization per channel
            mean = np.mean(data, axis=1, keepdims=True)
            std = np.std(data, axis=1, keepdims=True)
            std = np.where(std == 0, 1e-8, std)  # Avoid division by zero
            return (data - mean) / std

        elif self.normalization == 'minmax':
            # Min-max normalization per channel to [-1, 1]
            min_vals = np.min(data, axis=1, keepdims=True)
            max_vals = np.max(data, axis=1, keepdims=True)
            range_vals = max_vals - min_vals
            range_vals = np.where(range_vals == 0, 1e-8, range_vals)  # Avoid division by zero
            return 2 * (data - min_vals) / range_vals - 1

        else:
            return data

    def __len__(self):
        return len(self.subject_ids)  # Number of subjects, not files

    def __getitem__(self, idx):
        subject_id = self.subject_ids[idx]
        file_paths = self.subjects_data[subject_id]

        subject_eegs = []
        for file_path in file_paths:
            try:
                raw = mne.io.read_raw_bdf(file_path, preload=True, verbose=False)
                if raw.info['sfreq'] != 100:
                    raw.resample(100, verbose=False)

                data = raw.get_data()

                # Check for NaN values
                if np.isnan(data).any():
                    data = np.nan_to_num(data)

                # Apply normalization
                data = self._normalize_eeg(data)

                eeg_tensor = torch.tensor(data, dtype=torch.float32)

                if self.transform:
                    eeg_tensor = self.transform(eeg_tensor)

                subject_eegs.append(eeg_tensor)

            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                continue

        return {
            'subject_id': subject_id,
            'eeg_data': subject_eegs,  # List of tensors for all subject's files
            'num_files': len(subject_eegs)
        }


# Custom collate function for subject-based data
def subject_collate_fn(batch):
    """Collate function for subject-based dataset"""
    return {
        'subject_ids': [item['subject_id'] for item in batch],
        'eeg_data': [item['eeg_data'] for item in batch],  # List of lists of tensors
        'num_files': [item['num_files'] for item in batch]
    }
