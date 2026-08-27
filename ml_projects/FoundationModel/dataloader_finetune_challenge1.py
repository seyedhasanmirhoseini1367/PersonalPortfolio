import os
import glob
import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
import mne
import warnings

warnings.filterwarnings('ignore')

from typing import List, Tuple, Optional, Dict, Any

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


# ======================= EEG Fine-tune Dataset ==========================

class EEGFinetuneDataset(Dataset):
    """
    Dataset for fine-tuning on reaction time prediction
    - Creates 2-second windows aligned with stimulus events
    - Returns windowed EEG data with corresponding reaction times
    """

    def __init__(self, root_dirs: List[str], window_length_s: float = 2.0,
                 stimulus_offset_s: float = 0.5, sfreq: int = 100,
                 tasks: Optional[List[str]] = None, transform=None,
                 normalization: str = 'zscore', fit_normalization: bool = True):
        """
        Args:
            root_dirs: List of directories
            window_length_s: Window length in seconds (default: 2.0)
            stimulus_offset_s: Offset after stimulus onset (default: 0.5)
            sfreq: Sampling frequency (default: 100 Hz)
            tasks: Tasks to include (default: active tasks only)
            transform: Data transformation
            normalization: Type of normalization ('zscore', 'minmax', None)
            fit_normalization: Whether to compute normalization stats from entire dataset
        """
        self.window_length_s = window_length_s
        self.stimulus_offset_s = stimulus_offset_s
        self.sfreq = sfreq
        self.window_samples = int(window_length_s * sfreq)  # 200 samples
        self.offset_samples = int(stimulus_offset_s * sfreq)  # 50 samples
        self.transform = transform
        self.normalization = normalization
        self.fit_normalization = fit_normalization

        # Store normalization statistics
        self.global_mean = None
        self.global_std = None
        self.global_min = None
        self.global_max = None

        if tasks is None:
            # Default to active tasks for fine-tuning
            tasks = ['contrastChangeDetection']

        self.windows = []
        self.targets = []

        print(f"Creating windowed dataset for tasks: {tasks}")
        print(f"Window: {window_length_s}s ({self.window_samples} samples)")
        print(f"Offset: {stimulus_offset_s}s after stimulus")
        print(f"Using normalization: {normalization}")

        # First pass: collect all windows if normalization fitting is needed
        if fit_normalization and normalization is not None:
            self._collect_windows_for_normalization(root_dirs, tasks)

        # Second pass: process files with normalization
        for root_dir in root_dirs:
            if not os.path.exists(root_dir):
                continue

            participants_file = os.path.join(root_dir, 'participants.tsv')
            if os.path.exists(participants_file):
                participants_df = pd.read_csv(participants_file, sep='\t')
                participants_df['participant_id'] = participants_df['participant_id'].astype(str)
                row_map = {row['participant_id']: row for _, row in participants_df.iterrows()}
            else:
                row_map = {}

            subjects = [d for d in os.listdir(root_dir) if d.startswith('sub-')]

            for subject in subjects:
                eeg_dir = os.path.join(root_dir, subject, 'eeg')
                if not os.path.isdir(eeg_dir):
                    continue

                row = row_map.get(subject)
                for task in tasks:
                    if row is not None and not _subject_has_task(row, task):
                        continue
                    pattern = f"{subject}_task-{task}_*.bdf"
                    eeg_files = sorted(glob.glob(os.path.join(eeg_dir, pattern)))
                    for eeg_file in eeg_files:
                        self._process_file(eeg_file, task)

        print(f"Created {len(self.windows)} windows with targets")

    def _collect_windows_for_normalization(self, root_dirs: List[str], tasks: List[str]):
        """Collect all window data to compute global normalization statistics"""
        print("Computing global normalization statistics...")
        all_window_data = []

        for root_dir in root_dirs:
            if not os.path.exists(root_dir):
                continue

            participants_file = os.path.join(root_dir, 'participants.tsv')
            if os.path.exists(participants_file):
                participants_df = pd.read_csv(participants_file, sep='\t')
                participants_df['participant_id'] = participants_df['participant_id'].astype(str)
                row_map = {row['participant_id']: row for _, row in participants_df.iterrows()}
            else:
                row_map = {}

            subjects = [d for d in os.listdir(root_dir) if d.startswith('sub-')]

            for subject in subjects:
                eeg_dir = os.path.join(root_dir, subject, 'eeg')
                if not os.path.isdir(eeg_dir):
                    continue

                row = row_map.get(subject)
                for task in tasks:
                    if row is not None and not _subject_has_task(row, task):
                        continue
                    pattern = f"{subject}_task-{task}_*.bdf"
                    eeg_files = sorted(glob.glob(os.path.join(eeg_dir, pattern)))
                    for eeg_file in eeg_files:
                        all_window_data.extend(self._extract_windows_for_stats(eeg_file, task))

        if all_window_data:
            all_window_data = np.concatenate(all_window_data, axis=1)  # Combine all windows
            self.global_mean = np.mean(all_window_data, axis=1, keepdims=True)
            self.global_std = np.std(all_window_data, axis=1, keepdims=True)
            self.global_min = np.min(all_window_data, axis=1, keepdims=True)
            self.global_max = np.max(all_window_data, axis=1, keepdims=True)

            print("Global normalization statistics computed")

    def _extract_windows_for_stats(self, eeg_file: str, task: str) -> List[np.ndarray]:
        """Extract windows for normalization statistics computation"""
        windows = []
        try:
            raw = mne.io.read_raw_bdf(eeg_file, preload=True, verbose=False)
            if raw.info['sfreq'] != self.sfreq:
                raw.resample(self.sfreq)
            data = raw.get_data()

            # Load events
            events_file = eeg_file.replace('_eeg.bdf', '_events.tsv')
            if not os.path.exists(events_file):
                return windows

            events_df = pd.read_csv(events_file, sep='\t')
            trials = self._extract_trials(events_df)

            for trial in trials:
                stimulus_onset, response_onset, rt, correct = trial
                stim_sample = int(stimulus_onset * self.sfreq)
                window_start = stim_sample + self.offset_samples
                window_end = window_start + self.window_samples

                if window_end <= data.shape[1] and window_start >= 0:
                    window_data = data[:, window_start:window_end]
                    windows.append(window_data)

        except Exception as e:
            print(f"Error extracting windows for stats from {eeg_file}: {e}")

        return windows

    def _normalize_window(self, window_data: np.ndarray) -> np.ndarray:
        """Apply normalization to window data"""
        if self.normalization is None:
            return window_data

        if self.normalization == 'zscore':
            if self.fit_normalization and self.global_mean is not None:
                # Use global statistics
                std = np.where(self.global_std == 0, 1e-8, self.global_std)
                return (window_data - self.global_mean) / std
            else:
                # Use window-specific statistics
                mean = np.mean(window_data, axis=1, keepdims=True)
                std = np.std(window_data, axis=1, keepdims=True)
                std = np.where(std == 0, 1e-8, std)
                return (window_data - mean) / std

        elif self.normalization == 'minmax':
            if self.fit_normalization and self.global_min is not None:
                # Use global statistics
                range_vals = self.global_max - self.global_min
                range_vals = np.where(range_vals == 0, 1e-8, range_vals)
                return 2 * (window_data - self.global_min) / range_vals - 1
            else:
                # Use window-specific statistics
                min_vals = np.min(window_data, axis=1, keepdims=True)
                max_vals = np.max(window_data, axis=1, keepdims=True)
                range_vals = max_vals - min_vals
                range_vals = np.where(range_vals == 0, 1e-8, range_vals)
                return 2 * (window_data - min_vals) / range_vals - 1

        else:
            return window_data

    def _process_file(self, eeg_file: str, task: str):
        """Process single EEG file and extract windows"""
        try:
            # Load EEG data
            raw = mne.io.read_raw_bdf(eeg_file, preload=True, verbose=False)

            # Ensure 100 Hz
            if raw.info['sfreq'] != self.sfreq:
                raw.resample(self.sfreq)

            data = raw.get_data()  # (channels, samples)

            # Load events
            events_file = eeg_file.replace('_eeg.bdf', '_events.tsv')
            if not os.path.exists(events_file):
                return

            events_df = pd.read_csv(events_file, sep='\t')

            # Extract reaction time trials
            trials = self._extract_trials(events_df)

            # Create windows for each trial
            for trial in trials:
                stimulus_onset, response_onset, rt, correct = trial

                # Convert time to sample indices
                stim_sample = int(stimulus_onset * self.sfreq)
                window_start = stim_sample + self.offset_samples
                window_end = window_start + self.window_samples

                # Check bounds
                if window_end <= data.shape[1] and window_start >= 0:
                    # Extract window
                    window_data = data[:, window_start:window_end]

                    # Apply normalization
                    window_data = self._normalize_window(window_data)

                    # Store window and target
                    self.windows.append(torch.tensor(window_data, dtype=torch.float32))
                    self.targets.append({
                        'rt': rt,
                        'correct': correct,
                        'task': task,
                        'stimulus_onset': stimulus_onset,
                        'response_onset': response_onset
                    })

        except Exception as e:
            print(f"Error processing {eeg_file}: {e}")

    def _extract_trials(self, events_df: pd.DataFrame) -> List[Tuple[float, float, float, int]]:
        """Extract valid stimulus-response trials"""
        trials = []

        # Find button press events with feedback
        button_events = events_df[
            events_df['value'].str.contains('buttonPress', na=False) &
            events_df['feedback'].str.contains('face', na=False)
            ]

        for _, button_row in button_events.iterrows():
            button_idx = button_row.name
            button_onset = button_row['onset']
            feedback = button_row['feedback']

            # Look backward for most recent target
            target_events = events_df[
                (events_df.index < button_idx) &
                (events_df['value'].isin(['left_target', 'right_target']))
                ]

            if target_events.empty:
                continue

            # Get most recent target
            target_row = target_events.iloc[-1]
            target_onset = target_row['onset']

            # Calculate RT
            rt = button_onset - target_onset
            correct = 1 if feedback == 'smiley_face' else 0

            # Sanity check: RT should be positive and reasonable (0.1-5 seconds)
            if 0.1 <= rt <= 5.0:
                trials.append((target_onset, button_onset, rt, correct))

        return trials

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, idx):
        window = self.windows[idx]
        target = self.targets[idx]

        if self.transform:
            window = self.transform(window)

        return {
            'eeg': window,  # Shape: (129, 200)
            'rt': torch.tensor(target['rt'], dtype=torch.float32),
            'correct': torch.tensor(target['correct'], dtype=torch.long),
            'task': target['task'],
            'stimulus_onset': target['stimulus_onset'],
            'response_onset': target['response_onset']
        }
