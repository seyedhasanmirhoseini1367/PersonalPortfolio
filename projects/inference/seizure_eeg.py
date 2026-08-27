# projects/inference/seizure_eeg.py
"""
Inference handler for the EEG Seizure / LPD Detection project.

Pipeline
--------
1.  Read Parquet/CSV  →  drop EKG channel
2.  Take centre 10 seconds  (indices: centre±5000 at 200 Hz)
3.  Bandpass filter each channel  (0.5–30 Hz, Butterworth order 4)
4.  StandardScaler normalisation
5.  STFT spectrogram per channel  (nperseg=128, noverlap=64)
6.  Stack into tensor  (1, 19, freq_bins, time_steps)
7.  Load model  →  forward pass  →  softmax  →  predicted class

Model choices (set "model_variant" in file_input_config):
  "cnn_simple"       — Conv2d→BN→Conv2d→BN→MHA→LN→fc1→fc2 (default)
  "cnn_transformer"  — full CNN_Transformer_Classifier with spatial attention
  "gru_attention"    — GRU per-channel → self-attention classifier
  "fusion"           — CNN branch + GRU branch → fused self-attention classifier

Admin config (file_input_config):
{
  "handler":           "seizure_eeg",
  "model_variant":     "cnn_simple",
  "accepted_formats":  ["parquet", "csv"],
  "description":       "Upload a raw EEG Parquet file (19 EEG channels + EKG, 200 Hz).",
  "sampling_rate_hz":  200,
  "n_channels":        19,
  "nperseg":           128,
  "label_map":         {"0": "Seizure", "1": "LPD"}
}
"""

import os
import io
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, stft as scipy_stft
from sklearn.preprocessing import StandardScaler

from .registry import register
from .base import InferenceHandler, InferenceError

# Module-level cache: (model_path, variant, num_classes) → loaded model
_MODEL_CACHE: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# Signal processing  (matches training datasets exactly)
# ─────────────────────────────────────────────────────────────────────────────

def _butter_bandpass(lowcut=0.5, highcut=30.0, fs=200, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut / nyq, highcut / nyq], btype='band')
    return b, a


def _bandpass_filter(data: np.ndarray, lowcut=0.5, highcut=30.0, fs=200, order=4) -> np.ndarray:
    b, a = _butter_bandpass(lowcut, highcut, fs, order)
    return filtfilt(b, a, data)


def _create_stft_spectrogram(signal: np.ndarray, fs: int = 200,
                              nperseg: int = 128, noverlap: int = None) -> np.ndarray:
    """Matches create_stft_spectrogram from training code exactly."""
    if noverlap is None:
        noverlap = nperseg // 2
    if len(signal) < nperseg:
        raise InferenceError(
            f"Signal segment too short for STFT: {len(signal)} samples, "
            f"need at least {nperseg}."
        )
    _, _, spec = scipy_stft(signal, fs=fs, nperseg=nperseg, noverlap=noverlap)
    spec = np.abs(spec)
    mn, mx = spec.min(), spec.max()
    if mx > mn:
        spec = (spec - mn) / (mx - mn)
    spec = np.log1p(spec)
    return spec  # shape: (freq_bins, time_steps)


def _preprocess_eeg(df: pd.DataFrame, fs: int = 200, nperseg: int = 128,
                    n_channels: int = 19) -> np.ndarray:
    """
    Full CNN preprocessing pipeline:
      raw DataFrame → bandpass → scale → STFT per channel
    Returns tensor numpy array of shape (1, n_channels, freq_bins, time_steps).
    """
    total_samples = len(df)
    centre = total_samples // 2
    start  = max(centre - 1000, 0)
    end    = min(centre + 1000, total_samples)

    if (end - start) < nperseg:
        raise InferenceError(
            f"File has only {total_samples} samples — too short. "
            f"Need at least {nperseg} samples (≈ {nperseg/fs:.1f} s at {fs} Hz). "
            f"For best results upload ≥ 10 seconds of EEG ({10*fs} samples)."
        )

    segment = df.iloc[start:end, :n_channels].copy()

    filtered = pd.DataFrame(
        {col: _bandpass_filter(segment[col].values, fs=fs) for col in segment.columns},
        index=segment.index,
    )

    scaler   = StandardScaler()
    scaled   = pd.DataFrame(
        scaler.fit_transform(filtered),
        columns=filtered.columns,
    )

    spectrograms = []
    for i in range(min(n_channels, scaled.shape[1])):
        ch_data = scaled.iloc[:, i].values
        spec    = _create_stft_spectrogram(ch_data, fs=fs, nperseg=nperseg)
        spectrograms.append(spec)

    if len(spectrograms) < n_channels:
        raise InferenceError(
            f"File has {scaled.shape[1]} EEG channels, but the model expects {n_channels}. "
            "Check that you haven't accidentally dropped channels before uploading."
        )

    tensor = np.stack(spectrograms, axis=0)[np.newaxis, ...]
    return tensor.astype(np.float32)  # (1, n_channels, freq_bins, time_steps)


def _preprocess_for_gru(df: pd.DataFrame, fs: int = 200, n_channels: int = 19) -> np.ndarray:
    """
    GRU preprocessing pipeline: 10 non-overlapping 1-second windows.
      raw DataFrame → bandpass → scale → split into windows
    Returns tensor of shape (1, n_windows=10, n_channels, window_samples=200).
    """
    n_windows    = 10
    window_size  = fs  # 200 samples per second
    total_needed = n_windows * window_size  # 2000

    total_samples = len(df)
    if total_samples < total_needed:
        raise InferenceError(
            f"File has {total_samples} samples ({total_samples/fs:.1f} s). "
            f"The GRU/Fusion model needs ≥ {total_needed} samples "
            f"({n_windows} s at {fs} Hz). Please upload a longer segment."
        )

    # Centre crop to exactly total_needed samples
    centre = total_samples // 2
    start  = max(centre - total_needed // 2, 0)
    end    = start + total_needed
    if end > total_samples:
        start = max(total_samples - total_needed, 0)
        end   = start + total_needed

    segment = df.iloc[start:end, :n_channels].copy()

    filtered = pd.DataFrame(
        {col: _bandpass_filter(segment[col].values, fs=fs) for col in segment.columns},
        index=segment.index,
    )

    scaler = StandardScaler()
    scaled = scaler.fit_transform(filtered)  # (total_needed, n_channels)

    windows = []
    for i in range(n_windows):
        w = scaled[i * window_size:(i + 1) * window_size, :n_channels]  # (200, n_channels)
        windows.append(w.T)  # (n_channels, 200)

    tensor = np.stack(windows, axis=0)  # (10, 19, 200)
    return tensor[np.newaxis, ...].astype(np.float32)  # (1, 10, 19, 200)


# ─────────────────────────────────────────────────────────────────────────────
# Model architectures
# ─────────────────────────────────────────────────────────────────────────────

def _build_cnn_simple(num_classes: int = 2):
    """
    Reconstructed from the actual .pth weights (cnn_transformer_best_model90_22.pth).
    Input shape: (batch, n_channels, freq_bins, time_steps)
    """
    import torch.nn as nn
    import torch

    class CNNSimple(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Sequential(
                nn.Conv2d(1, 64, kernel_size=7, padding=3),
                nn.BatchNorm2d(64),
                nn.GELU(),
                nn.MaxPool2d(2, 2),
            )
            self.conv2 = nn.Sequential(
                nn.Conv2d(64, 128, kernel_size=5, padding=2),
                nn.BatchNorm2d(128),
                nn.GELU(),
                nn.MaxPool2d(2, 2),
            )
            self.global_pool    = nn.AdaptiveAvgPool2d((1, 1))
            self.self_attention = nn.MultiheadAttention(embed_dim=128, num_heads=4,
                                                        batch_first=True)
            self.layer_norm     = nn.LayerNorm(128)
            self.fc1            = nn.Linear(128, 64)
            self.fc2            = nn.Linear(64, num_classes)
            self.dropout        = nn.Dropout(0.3)

        def forward(self, x):
            batch, n_ch, freq, time = x.shape
            ch_features = []
            for c in range(n_ch):
                ch = x[:, c:c+1, :, :]
                ch = self.conv1(ch)
                ch = self.conv2(ch)
                ch = self.global_pool(ch)
                ch = ch.squeeze(-1).squeeze(-1)
                ch_features.append(ch)
            seq = torch.stack(ch_features, dim=1)
            attn_out, _ = self.self_attention(seq, seq, seq)
            out = self.layer_norm(attn_out.mean(dim=1))
            out = self.dropout(torch.relu(self.fc1(out)))
            return self.fc2(out)

    return CNNSimple()


def _build_cnn_transformer(num_classes: int = 2):
    """
    Full CNN_Transformer_Classifier with spatial attention gates.
    Input shape: (batch, n_channels, freq_bins, time_steps)
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class PositionalEncoding(nn.Module):
        def __init__(self, d_model, max_len=5000):
            super().__init__()
            if d_model % 2 != 0:
                d_model += 1
            pe = torch.zeros(max_len, d_model)
            pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div = torch.exp(torch.arange(0, d_model, 2).float() * -(np.log(10000.0) / d_model))
            pe[:, 0::2] = torch.sin(pos * div)
            pe[:, 1::2] = torch.cos(pos * div)
            self.register_buffer('pe', pe.unsqueeze(0))

        def forward(self, x):
            return x + self.pe[:, :x.size(1), :x.size(2)]

    class CNNTransformerClassifier(nn.Module):
        def __init__(self, in_channels=1,
                     cnn_out_channels=(32, 16, 8),
                     cnn_kernel_sizes=((5,5),(3,3),(3,3)),
                     cnn_paddings=((1,1),(2,2),(3,3)),
                     d_model=100, num_heads=4,
                     num_transformer_layers=2, dropout_rate=0.5,
                     num_classes=2, num_eeg_channels=19):
            super().__init__()
            self.num_eeg_channels = num_eeg_channels

            def conv_block(in_ch, out_ch, k, p):
                return nn.Sequential(
                    nn.Conv2d(in_ch, out_ch, k, padding=p),
                    nn.BatchNorm2d(out_ch), nn.GELU(),
                    nn.MaxPool2d(2, 2),
                )

            self.conv1 = conv_block(in_channels, cnn_out_channels[0],
                                    cnn_kernel_sizes[0], cnn_paddings[0])
            self.conv2 = conv_block(cnn_out_channels[0], cnn_out_channels[1],
                                    cnn_kernel_sizes[1], cnn_paddings[1])
            self.conv3 = nn.Sequential(
                nn.Conv2d(cnn_out_channels[1], cnn_out_channels[2],
                          cnn_kernel_sizes[2], padding=cnn_paddings[2]),
                nn.BatchNorm2d(cnn_out_channels[2]), nn.GELU(),
            )
            self.sa1 = nn.Sequential(nn.Conv2d(cnn_out_channels[0], 1, 1), nn.Sigmoid())
            self.sa2 = nn.Sequential(nn.Conv2d(cnn_out_channels[1], 1, 1), nn.Sigmoid())
            self.sa3 = nn.Sequential(nn.Conv2d(cnn_out_channels[2], 1, 1), nn.Sigmoid())
            self.pool = nn.AdaptiveAvgPool2d((1, 1))
            self.feature_fusion = nn.Linear(sum(cnn_out_channels), d_model)
            self.pos_encoder = PositionalEncoding(d_model)
            enc_layer = nn.TransformerEncoderLayer(d_model, num_heads,
                                                   dropout=dropout_rate)
            self.transformer  = nn.TransformerEncoder(enc_layer, num_transformer_layers)
            self.layer_norm   = nn.LayerNorm(d_model)
            self.fc1          = nn.Linear(d_model, d_model // 2)
            self.out          = nn.Linear(d_model // 2, num_classes)
            self.dropout      = nn.Dropout(dropout_rate)

        def forward(self, x):
            batch, n_ch, freq, time = x.shape
            ch_outs = []
            for c in range(n_ch):
                cd = x[:, c:c+1, :, :]
                o1 = self.conv1(cd);   o1 = o1 * self.sa1(o1)
                o2 = self.conv2(o1);   o2 = o2 * self.sa2(o2)
                o3 = self.conv3(o2);   o3 = o3 * self.sa3(o3)
                f1 = self.pool(o1).squeeze(-1).squeeze(-1)
                f2 = self.pool(o2).squeeze(-1).squeeze(-1)
                f3 = self.pool(o3).squeeze(-1).squeeze(-1)
                ch_outs.append(torch.cat([f1, f2, f3], dim=1))
            feats = torch.stack(ch_outs, dim=1)
            t = self.pos_encoder(self.feature_fusion(feats))
            t = self.transformer(t.permute(1, 0, 2)).mean(0)
            t = self.layer_norm(t)
            return self.out(self.dropout(F.relu(self.fc1(t))))

    return CNNTransformerClassifier(num_classes=num_classes)


def _build_gru_attention_from_state_dict(state_dict: dict, num_classes: int = 2):
    """
    Reconstruct the GRU+attention model by reading weight shapes directly from
    the checkpoint. Handles:
      - Uni/bidirectional GRU
      - input_norm_gru (BatchNorm, detected via running_mean presence)
      - gru_norm (LayerNorm or BatchNorm, detected via running_mean presence)
      - Optional projection linear
      - Skip connection: if classification_head input == 2*embed_dim, the
        forward concatenates gru-mean and attn-mean before the head
    """
    import torch
    import torch.nn as nn

    # ── GRU ──────────────────────────────────────────────────────────────────
    ih         = state_dict['gru.weight_ih_l0']
    gru_in     = int(ih.shape[1])
    gru_hidden = int(ih.shape[0]) // 3
    bidir      = 'gru.weight_ih_l0_reverse' in state_dict
    gru_out    = gru_hidden * (2 if bidir else 1)

    # ── Input norm (BatchNorm if has running_mean, else LayerNorm) ────────────
    has_in_norm    = 'input_norm_gru.weight' in state_dict
    in_norm_is_bn  = has_in_norm and 'input_norm_gru.running_mean' in state_dict
    in_norm_size   = int(state_dict['input_norm_gru.weight'].shape[0]) if has_in_norm else None

    # ── GRU output norm (same detection logic) ────────────────────────────────
    has_gru_norm   = 'gru_norm.weight' in state_dict
    gru_norm_is_bn = has_gru_norm and 'gru_norm.running_mean' in state_dict
    gru_norm_size  = int(state_dict['gru_norm.weight'].shape[0]) if has_gru_norm else None

    # ── Optional projection ───────────────────────────────────────────────────
    has_proj = 'projection.weight' in state_dict
    proj_out = int(state_dict['projection.weight'].shape[0]) if has_proj else gru_out

    # ── Self-attention ────────────────────────────────────────────────────────
    embed_dim = int(state_dict['self_attention.in_proj_weight'].shape[1])
    num_heads = 4 if embed_dim % 4 == 0 else (2 if embed_dim % 2 == 0 else 1)

    # ── Classification head ───────────────────────────────────────────────────
    cl_in     = int(state_dict['classification_head.0.weight'].shape[1])
    cl_hidden = int(state_dict['classification_head.0.weight'].shape[0])
    # If input to head is 2×embed_dim the forward concatenates gru-mean + attn-mean
    use_skip  = (cl_in == 2 * embed_dim)

    class GRUAttentionModel(nn.Module):
        def __init__(self):
            super().__init__()
            if has_in_norm:
                self.input_norm_gru = (nn.BatchNorm1d(in_norm_size) if in_norm_is_bn
                                       else nn.LayerNorm(in_norm_size))
            self.gru = nn.GRU(input_size=gru_in, hidden_size=gru_hidden,
                              batch_first=True, bidirectional=bidir)
            if has_gru_norm:
                self.gru_norm = (nn.BatchNorm1d(gru_norm_size) if gru_norm_is_bn
                                 else nn.LayerNorm(gru_norm_size))
            if has_proj:
                self.projection = nn.Linear(gru_out, proj_out)
            self.self_attention = nn.MultiheadAttention(
                embed_dim=embed_dim, num_heads=num_heads, batch_first=True)
            self.classification_head = nn.Sequential(
                nn.Linear(cl_in, cl_hidden),
                nn.LayerNorm(cl_hidden),
                nn.GELU(),
                nn.Dropout(0.5),
                nn.Linear(cl_hidden, num_classes),
            )

        def forward(self, x):
            # x: (batch, seq_len, n_channels, input_size)
            batch_size, seq_len, num_channels, input_size = x.shape

            # Permute → (batch, n_channels, seq_len, input_size), flatten for GRU
            x = x.permute(0, 2, 1, 3).contiguous()
            x = x.reshape(batch_size * num_channels, seq_len, input_size)

            if has_in_norm:
                if in_norm_is_bn:
                    B_C, S, F = x.shape
                    x = self.input_norm_gru(x.reshape(B_C * S, F)).reshape(B_C, S, F)
                else:
                    x = self.input_norm_gru(x)

            gru_out, _ = self.gru(x)
            last = gru_out[:, -1, :]                            # (B*C, gru_out)

            if has_gru_norm:
                last = self.gru_norm(last)

            last = last.reshape(batch_size, num_channels, -1)  # (B, C, gru_out)

            if has_proj:
                last = self.projection(last)                    # (B, C, proj_out)

            attn_out, _ = self.self_attention(last, last, last) # (B, C, embed_dim)

            if use_skip:
                # Concatenate mean-pooled GRU features with mean-pooled attention features
                pooled = torch.cat([last.mean(dim=1), attn_out.mean(dim=1)], dim=-1)
            else:
                pooled = attn_out.mean(dim=1)                   # (B, embed_dim)

            return self.classification_head(pooled)

    return GRUAttentionModel()


def _build_fusion_classifier(num_classes: int = 2):
    """
    CNN branch + GRU branch → fused self-attention → classifier.
    cnnx  shape: (batch, freq_bins=65, n_channels=19, time_steps=31)
    lstmx shape: (batch, seq_len=10, n_channels=19, input_size=200)
    """
    import torch
    import torch.nn as nn

    class FusionClassifier(nn.Module):
        def __init__(self):
            super().__init__()
            # CNN branch — processes per-channel STFT spectrograms
            self.conv_layers = nn.Sequential(
                nn.Conv2d(1, 64, kernel_size=7, padding=3),
                nn.BatchNorm2d(64), nn.GELU(), nn.MaxPool2d(2),
                nn.Conv2d(64, 96, kernel_size=5, padding=2),
                nn.BatchNorm2d(96), nn.GELU(), nn.MaxPool2d(2),
            )
            self.adaptive_pool = nn.AdaptiveAvgPool2d((1, 1))
            # GRU branch
            self.gru = nn.GRU(input_size=200, hidden_size=32, batch_first=True)
            # Fusion (96 CNN + 32 GRU = 128)
            self.embedding = nn.Linear(128, 128)
            self.self_attention = nn.MultiheadAttention(
                embed_dim=128, num_heads=4, batch_first=True)
            self.layer_norm = nn.LayerNorm(128)
            self.dropout    = nn.Dropout(0.5)
            self.classifier = nn.Sequential(
                nn.Linear(128, 64),
                nn.GELU(),
                nn.Dropout(0.5),
                nn.Linear(64, num_classes),
            )

        def forward(self, cnnx, lstmx):
            # cnnx: (batch, height=freq_bins, num_channels, width=time_steps)
            batch_size, height, num_channels, width = cnnx.shape
            # permute → (B, C, H, W) then flatten batch+channel for conv
            cnnx = cnnx.permute(0, 2, 1, 3).contiguous()
            cnnx = cnnx.reshape(batch_size * num_channels, 1, height, width)
            cnnx = self.conv_layers(cnnx)
            cnnx = self.adaptive_pool(cnnx)
            cnn_out = cnnx.reshape(batch_size, num_channels, -1)  # (B, C, 96)

            # lstmx: (batch, seq_len, num_channels, input_size)
            batch_size_l, seq_len, num_channels_l, input_size = lstmx.shape
            # permute → (B, C, S, F) then flatten batch+channel for GRU
            lstmx = lstmx.permute(0, 2, 1, 3).contiguous()
            lstmx = lstmx.reshape(batch_size_l * num_channels_l, seq_len, input_size)
            gru_out, _ = self.gru(lstmx)
            gru_out = gru_out[:, -1, :]
            gru_out = gru_out.reshape(batch_size, num_channels, -1)  # (B, C, 32)

            fused = torch.cat((cnn_out, gru_out), dim=-1)  # (B, C, 128)
            fused = self.embedding(fused)
            attn_out, _ = self.self_attention(fused, fused, fused)
            attn_out = self.layer_norm(attn_out.mean(dim=1))
            attn_out = self.dropout(attn_out)
            return self.classifier(attn_out)

    return FusionClassifier()


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────

@register("seizure_eeg")
class SeizureEEGHandler(InferenceHandler):

    accepted_extensions = ["parquet", "csv"]
    DROP_COLS = ["EKG"]

    # LabelEncoder sorts alphabetically: LPD=0, Seizure=1
    DEFAULT_LABEL_MAP = {"0": "LPD (Lateralised Periodic Discharge)",
                         "1": "Seizure"}

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)
        max_mb = self.cfg.get("max_file_mb", 200)
        if hasattr(file, "size") and file.size > max_mb * 1024 * 1024:
            raise InferenceError(
                f"File is too large ({file.size / 1e6:.0f} MB). "
                f"Maximum allowed: {max_mb} MB."
            )

    def load_and_preprocess(self, file, filename: str):
        # ── 1. Parse file ─────────────────────────────────────────────────────
        try:
            if filename.endswith(".parquet"):
                df = pd.read_parquet(io.BytesIO(file.read()))
            else:
                df = pd.read_csv(file)
        except Exception as e:
            raise InferenceError(f"Could not read file: {e}")

        original_cols = list(df.columns)
        n_original    = len(df)

        # ── 2. Drop non-EEG columns ───────────────────────────────────────────
        drop = [c for c in self.DROP_COLS if c in df.columns]
        if drop:
            df = df.drop(columns=drop)

        # ── 3. Validate channel count ─────────────────────────────────────────
        n_channels = self.cfg.get("n_channels", 19)
        fs         = int(self.cfg.get("sampling_rate_hz", 200))
        nperseg    = int(self.cfg.get("nperseg", 128))

        if df.shape[1] < n_channels:
            raise InferenceError(
                f"Not enough EEG channels. Found {df.shape[1]} columns "
                f"(after dropping {drop}), but the model needs {n_channels}. "
                f"Your file columns: {original_cols}."
            )

        expected_ch = self.cfg.get("expected_channels")
        if expected_ch:
            missing = [c for c in expected_ch if c not in df.columns]
            if missing:
                raise InferenceError(
                    f"Missing EEG channels: {missing}. "
                    f"Your file has: {list(df.columns)}."
                )
            df = df[expected_ch]

        # ── 4. Sample-count sanity check ──────────────────────────────────────
        min_samples = nperseg * 2
        if len(df) < min_samples:
            raise InferenceError(
                f"File has only {len(df)} samples "
                f"({len(df)/fs:.1f} s at {fs} Hz). "
                f"Minimum required: {min_samples} samples "
                f"({min_samples/fs:.1f} s). "
                "Please upload a longer EEG segment."
            )

        # ── 5. Run preprocessing pipelines ───────────────────────────────────
        try:
            tensor = _preprocess_eeg(df, fs=fs, nperseg=nperseg,
                                     n_channels=n_channels)
        except InferenceError:
            raise
        except Exception as e:
            raise InferenceError(f"Preprocessing failed: {e}")

        self._tensor = tensor

        # Compute GRU windows tensor for variants that need it
        variant = self.cfg.get("model_variant", "cnn_simple")
        if variant in ("gru_attention", "fusion"):
            try:
                self._gru_tensor = _preprocess_for_gru(df, fs=fs,
                                                       n_channels=n_channels)
            except InferenceError:
                raise
            except Exception as e:
                raise InferenceError(f"GRU preprocessing failed: {e}")
        else:
            self._gru_tensor = None

        # ── 6. Build input summary ────────────────────────────────────────────
        _, n_ch, freq_bins, time_steps = tensor.shape
        input_summary = {
            "format":           "Parquet" if filename.endswith(".parquet") else "CSV",
            "total_samples":    n_original,
            "duration_sec":     round(n_original / fs, 1),
            "sampling_rate_hz": fs,
            "eeg_channels":     n_ch,
            "dropped_columns":  drop,
            "segment_used":     "centre 10 s",
            "spectrogram_shape": f"{freq_bins} freq bins × {time_steps} time steps",
            "preprocessing":    f"bandpass 0.5–30 Hz → StandardScaler → STFT (nperseg={nperseg})",
        }

        self._input_summary_n_original = n_original
        placeholder = pd.DataFrame([{"tensor_ready": True}])
        return placeholder, input_summary

    def postprocess(self, raw_prediction, proba, feature_df):
        label_map  = {**self.DEFAULT_LABEL_MAP, **self.cfg.get("label_map", {})}
        pred_val   = self._pred_val
        confidence = self._proba
        label      = label_map.get(str(pred_val), str(pred_val))
        return {
            "prediction":       pred_val,
            "prediction_label": label,
            "prediction_proba": confidence,
        }

    def run(self, uploaded_file) -> dict:
        """
        Override base run() — onnxruntime inference with per-variant dispatch.
        Variants: cnn_simple, cnn_transformer, gru_attention, fusion.
        """
        import onnxruntime as ort

        filename    = uploaded_file.name.lower()
        variant     = self.cfg.get("model_variant", "cnn_simple")

        # ── Validate + preprocess ─────────────────────────────────────────────
        self.validate_file(uploaded_file, filename)
        feature_df, input_summary = self.load_and_preprocess(uploaded_file, filename)

        # ── Load ONNX session ─────────────────────────────────────────────────
        model_path = self.project.get_model_path()
        if not model_path or not os.path.exists(model_path):
            raise InferenceError(
                "Model file not found on the server. "
                "Please ask the site owner to upload the trained model via Django admin."
            )

        # ONNX models are committed to projects/models/ (media/ is gitignored)
        _code_models = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
        onnx_path = os.path.join(_code_models, f"{variant}.onnx")
        if not os.path.exists(onnx_path):
            raise InferenceError(
                f"ONNX model not found at {onnx_path}. "
                "Please run scripts/convert_to_onnx.py to generate ONNX models."
            )

        session = _MODEL_CACHE.get(onnx_path)
        if session is None:
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            session = ort.InferenceSession(
                onnx_path, sess_options=opts, providers=['CPUExecutionProvider']
            )
            _MODEL_CACHE[onnx_path] = session

        # ── Inference — dispatch by variant ───────────────────────────────────
        if variant == "gru_attention":
            logits = session.run(['logits'], {'x': self._gru_tensor})[0]

        elif variant == "fusion":
            cnn_permuted = np.transpose(self._tensor, (0, 2, 1, 3))
            logits = session.run(['logits'], {'cnnx': cnn_permuted, 'lstmx': self._gru_tensor})[0]

        else:  # cnn_simple, cnn_transformer
            logits = session.run(['logits'], {'x': self._tensor})[0]

        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs      = e / e.sum(axis=1, keepdims=True)
        pred_idx   = int(np.argmax(probs[0]))
        confidence = float(probs[0, pred_idx])

        self._pred_val = pred_idx
        self._proba    = confidence

        # ── Build final result ────────────────────────────────────────────────
        result = self.postprocess(None, confidence, feature_df)
        result["success"]       = True
        result["input_summary"] = input_summary

        spec_sample = self._tensor[0, 0, :, :5].flatten()[:20]
        result["input_data"] = {
            f"ch0_spec_f{i}": round(float(v), 5)
            for i, v in enumerate(spec_sample)
        }
        result["input_data"]["n_channels"]    = self._tensor.shape[1]
        result["input_data"]["freq_bins"]     = self._tensor.shape[2]
        result["input_data"]["time_steps"]    = self._tensor.shape[3]
        result["input_data"]["predicted_idx"] = pred_idx
        result["input_data"]["confidence"]    = round(confidence, 4)

        return result
