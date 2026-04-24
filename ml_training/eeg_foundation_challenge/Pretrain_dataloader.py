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


# ======================= EEG Pretrain Dataset ==========================
class EEGPretrainDataset(Dataset):
    """
    Dataset for pre-training foundation model
    - Loads full EEG signals from all tasks
    - No windowing, no targets needed
    - Returns only EEG data tensors for self-supervised learning
    """

    def __init__(self, root_dirs: List[str], tasks: Optional[List[str]] = None, transform=None,
                 normalization: str = 'zscore'):
        self.transform = transform
        self.eeg_files = []
        self.tasks = tasks
        self.normalization = normalization  # 'zscore', 'minmax', or None

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

            subjects = [sub for sub in os.listdir(root_dir) if sub.startswith('sub-')]
            for subject in subjects:
                task_path = os.path.join(root_dir, subject, 'eeg')
                if not os.path.exists(task_path):
                    continue

                for task in self.tasks:
                    pattern = f"{subject}_task-{task}*eeg.bdf"
                    eeg_files = glob.glob(os.path.join(task_path, pattern))
                    self.eeg_files.extend(eeg_files)

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
            data, times = raw.get_data(return_times=True)

            # Check for NaN values
            if np.isnan(data).any():
                print(f"Warning: NaN values found in {eeg_path}, using zeros")
                data = np.nan_to_num(data)

            # Apply normalization
            data = self._normalize_eeg(data)

            eeg_tensor = torch.tensor(data, dtype=torch.float32)

            if self.transform:
                eeg_tensor = self.transform(eeg_tensor)

            return eeg_tensor

        except Exception as e:
            print(f"Error loading {eeg_path}: {e}")


def pretrain_collate_fn(batch):
    """Custom collate function for pre-training dataset - only EEG data"""
    # Find max sequence length in batch
    max_length = max([item.shape[1] for item in batch])

    # Pad sequences
    padded_eeg = []
    for eeg in batch:
        if eeg.shape[1] < max_length:
            padding = torch.zeros(eeg.shape[0], max_length - eeg.shape[1])
            eeg = torch.cat([eeg, padding], dim=1)
        padded_eeg.append(eeg)

    return torch.stack(padded_eeg)


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

            subjects = [sub for sub in os.listdir(root_dir) if sub.startswith('sub-')]
            for subject in subjects:
                task_path = os.path.join(root_dir, subject, 'eeg')
                if not os.path.exists(task_path):
                    continue

                subject_files = []
                for task in tasks:
                    pattern = f"{subject}_task-{task}*eeg.bdf"
                    eeg_files = glob.glob(os.path.join(task_path, pattern))
                    subject_files.extend(eeg_files)

                if subject_files:  # Only add subjects with files
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
