# augmentations.py
# EEG-specific augmentations and multi-crop view generator
# Produces 2 global + 4 local crops by default.

import random
import numpy as np
import torch
import torch.nn.functional as F


class EEGAugmentor:
    """
    Create physiologically-plausible augmentations and multi-crop views.
    Input signal shape: (channels, time) as np.ndarray or torch.Tensor
    """

    def __init__(
        self,
        sr: int = 100,
        global_duration_s: float = 4.0,
        local_duration_s: float = 0.8,
        n_global: int = 2,
        n_local: int = 4,
        max_time_jitter_s: float = 0.2,
        channel_dropout_prob: float = 0.02,
        noise_std: float = 0.005,
        seed: int = 42
    ):
        self.sr = sr
        self.global_len = int(global_duration_s * sr)
        self.local_len = int(local_duration_s * sr)
        self.n_global = n_global
        self.n_local = n_local
        self.max_jitter = int(max_time_jitter_s * sr)
        self.channel_dropout_prob = channel_dropout_prob
        self.noise_std = noise_std
        random.seed(seed)

    def _to_tensor(self, x):
        if isinstance(x, np.ndarray):
            x = torch.from_numpy(x).float()
        return x

    def random_time_shift(self, x):
        shift = random.randint(-self.max_jitter, self.max_jitter)
        if shift == 0:
            return x
        return torch.roll(x, shifts=shift, dims=-1)

    def channel_dropout(self, x):
        x = x.clone()
        channels = x.shape[0]
        mask = torch.rand(channels) > self.channel_dropout_prob
        return x * mask.view(-1, 1)

    def gaussian_noise(self, x):
        noise = torch.randn_like(x) * self.noise_std
        return x + noise

    def amplitude_scaling(self, x, scale_range=(0.9, 1.1)):
        s = random.uniform(scale_range[0], scale_range[1])
        return x * s

    def time_mask(self, x, width_samples=None):
        if width_samples is None:
            width = int(0.1 * x.shape[-1])
        else:
            width = width_samples
        x = x.clone()
        if x.shape[-1] <= width:
            return x
        start = random.randint(0, x.shape[-1] - width)
        x[:, start:start + width] = 0.0
        return x

    def apply_random_augment(self, x):
        x = self._to_tensor(x)
        if random.random() < 0.7:
            x = self.random_time_shift(x)
        if random.random() < 0.5:
            x = self.channel_dropout(x)
        if random.random() < 0.6:
            x = self.gaussian_noise(x)
        if random.random() < 0.4:
            x = self.amplitude_scaling(x)
        if random.random() < 0.3:
            x = self.time_mask(x)
        return x

    def _crop_random(self, x, length):
        total = x.shape[-1]
        if length >= total:
            if length == total:
                return x.clone()
            pad = length - total
            return torch.cat([x, torch.zeros(x.shape[0], pad, dtype=x.dtype)], dim=-1)
        start = random.randint(0, total - length)
        return x[:, start:start + length].clone()

    def multiview(self, x):
        x = self._to_tensor(x)
        views = []
        # Global crops
        for _ in range(self.n_global):
            crop = self._crop_random(x, self.global_len)
            crop = self.apply_random_augment(crop)
            views.append(crop)
        # Local crops
        for _ in range(self.n_local):
            crop = self._crop_random(x, self.local_len)
            crop = self.apply_random_augment(crop)
            views.append(crop)
        return views

    def generate_mask_indices(self, n_patches: int, mask_ratio: float = 0.6):
        """
        Return a boolean mask of shape (n_patches,) where True indicates masked patch.
        """
        n_mask = int(round(n_patches * mask_ratio))
        all_idx = list(range(n_patches))
        masked = set(random.sample(all_idx, n_mask))
        mask = [i in masked for i in range(n_patches)]
        return torch.tensor(mask, dtype=torch.bool)
