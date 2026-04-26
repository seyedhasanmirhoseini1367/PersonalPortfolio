# projects/inference/eeg_foundation.py
"""
Inference handlers for NeurIPS 2025 EEG Foundation Model Challenge.

Challenge 1 — handler slug: "eeg_rt_predictor"
    Input : CSV (129 rows × 200 cols) or NPY (129, 200)
            One 2-second z-scored EEG window at 100 Hz, 129 channels.
    Output: predicted reaction time (ms) for a contrast-change-detection trial.

Challenge 2 — handler slug: "eeg_externalizing_predictor"
    Input : same format
    Output: predicted externalizing factor score (z-score, population-normalised).

Both handlers load their inference bundle (.pt file) which contains:
  model_state_dict, model_config, task_name, normalization, sfreq, metrics.

Admin config (file_input_config) example:
{
  "handler":            "eeg_rt_predictor",
  "model_bundle_path":  "/absolute/path/to/weights_challenge_1.pt",
  "sample_data_path":   "/absolute/path/to/sample_eeg_ch1.npy",
  "description":        "Upload a 129×200 CSV or NPY EEG window."
}
"""

import os
import io
import sys
import numpy as np
import pandas as pd

import torch

from .registry import register
from .base import InferenceHandler, InferenceError

# ── shared path to the pretrain_model.py (so we can reconstruct EEGFoundationModel) ──
_ML_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'ml_training', 'FoundationModel')


def _load_foundation_model(bundle_path: str, task_name: str):
    """
    Load EEGFoundationModel from an inference bundle produced by the trainers.
    Returns (model, bundle_meta).
    """
    bundle = torch.load(bundle_path, map_location='cpu', weights_only=False)
    cfg    = bundle['model_config']

    # Import pretrain_model from the ml_training directory
    if _ML_DIR not in sys.path:
        sys.path.insert(0, _ML_DIR)
    from pretrain_model import EEGFoundationModel  # noqa: E402

    model = EEGFoundationModel(
        n_channels      = cfg['n_channels'],
        patch_size       = cfg['patch_size'],
        d_model          = cfg['d_model'],
        n_heads          = cfg['n_heads'],
        n_encoder_layers = cfg['n_encoder_layers'],
        n_decoder_layers = cfg['n_decoder_layers'],
        dim_feedforward  = cfg['dim_feedforward'],
        dropout          = cfg['dropout'],
    )
    model.add_task_head(task_name, 'regression', output_dim=1)
    model.load_state_dict(bundle['model_state_dict'], strict=False)
    model.eval()
    return model, bundle


def _parse_eeg_input(file, filename: str) -> np.ndarray:
    """
    Parse uploaded file into a float32 numpy array of shape (129, 200).
    Accepts .npy or .csv.
    """
    if filename.endswith('.npy'):
        try:
            arr = np.load(io.BytesIO(file.read())).astype(np.float32)
        except Exception as e:
            raise InferenceError(f"Could not load NPY file: {e}")
    elif filename.endswith('.csv'):
        try:
            df  = pd.read_csv(file, header=None)
            arr = df.values.astype(np.float32)
        except Exception as e:
            raise InferenceError(f"Could not read CSV: {e}")
    else:
        raise InferenceError("Please upload a .npy or .csv file (shape 129 channels × 200 samples).")

    if arr.ndim != 2:
        raise InferenceError(
            f"Expected a 2-D array (channels × samples), got shape {arr.shape}."
        )
    if arr.shape[0] != 129:
        # try transpose
        if arr.shape[1] == 129:
            arr = arr.T
        else:
            raise InferenceError(
                f"Expected 129 EEG channels. Got shape {arr.shape}. "
                "The array must be (129, 200) — channels as rows."
            )
    if arr.shape[1] < 200:
        raise InferenceError(
            f"Need at least 200 time samples (2 s at 100 Hz). Got {arr.shape[1]}."
        )
    # take first 200 samples if longer
    arr = arr[:, :200]
    return arr


def _zscore(arr: np.ndarray) -> np.ndarray:
    mean = arr.mean(axis=1, keepdims=True)
    std  = arr.std(axis=1,  keepdims=True)
    std[std == 0] = 1e-8
    return (arr - mean) / std


# ─────────────────────────────────────────────────────────────────────────────
# Base handler shared by both challenges
# ─────────────────────────────────────────────────────────────────────────────

class _EEGFoundationBase(InferenceHandler):
    accepted_extensions = ['npy', 'csv']
    task_name: str = ''           # set by subclass
    result_label_template: str = ''

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)

    def load_and_preprocess(self, file, filename: str):
        arr = _parse_eeg_input(file, filename)
        arr = _zscore(arr)

        input_summary = {
            'format':       'NPY' if filename.endswith('.npy') else 'CSV',
            'shape':        f'{arr.shape[0]} channels × {arr.shape[1]} samples',
            'duration':     '2.0 s at 100 Hz',
            'normalization':'z-score per channel',
            'channels':     129,
            'samples':      200,
        }
        self._arr = arr
        # Placeholder so base._validate_features is a no-op
        return pd.DataFrame([{'ready': True}]), input_summary

    def run(self, uploaded_file) -> dict:
        filename = uploaded_file.name.lower()
        self.validate_file(uploaded_file, filename)
        _, input_summary = self.load_and_preprocess(uploaded_file, filename)
        return self._infer(input_summary)

    def run_sample(self) -> dict:
        """Run inference on the pre-saved sample window (no file upload needed)."""
        sample_path = self.cfg.get('sample_data_path', '')
        if not sample_path or not os.path.exists(sample_path):
            # fall back to the npy file shipped next to this module
            default = os.path.join(
                os.path.dirname(__file__),
                f'sample_eeg_{"ch1" if self.task_name == "rt" else "ch2"}.npy',
            )
            sample_path = default

        if not os.path.exists(sample_path):
            raise InferenceError("Sample data file not found on server.")

        arr = np.load(sample_path).astype(np.float32)
        arr = _zscore(arr)
        self._arr = arr
        input_summary = {
            'format':       'pre-saved sample (NPY)',
            'shape':        f'{arr.shape[0]} channels × {arr.shape[1]} samples',
            'duration':     '2.0 s at 100 Hz',
            'normalization':'z-score per channel',
            'note':         'Demo sample from HBN-EEG dataset (anonymised)',
        }
        return self._infer(input_summary)

    def _infer(self, input_summary: dict) -> dict:
        # ── Option 1: Azure ML endpoint (fast, scalable) ──────────────────────
        # If EEG_RT_ENDPOINT_URL / EEG_EXT_ENDPOINT_URL are set in Django settings,
        # the prediction is served by the cloud endpoint instead of local inference.
        # Falls back to local if not configured or unreachable.
        try:
            from .azure_ml_client import AzureMLClient
            client = AzureMLClient.for_task(self.task_name)
            if client.is_configured:
                azure_result = client.predict({"data": self._arr.tolist()})
                if azure_result and 'prediction' in azure_result:
                    pred   = float(azure_result['prediction'])
                    bundle = {}  # no local bundle needed
                    label, extra = self._format_prediction(pred, bundle)
                    return {
                        'success':          True,
                        'prediction':       round(pred, 4),
                        'prediction_label': label,
                        'prediction_proba': None,
                        'input_summary':    {**input_summary, 'inference_backend': 'Azure ML'},
                        'input_data':       {'n_channels': 129, 'task': self.task_name, **extra},
                    }
        except Exception:
            pass  # fall through to local inference

        # ── Option 2: Local inference (default) ───────────────────────────────
        bundle_path = self.cfg.get('model_bundle_path', '')
        if not bundle_path or not os.path.exists(bundle_path):
            raise InferenceError(
                "Model bundle not found on server. "
                "Set model_bundle_path in file_input_config via Django admin."
            )

        try:
            model, bundle = _load_foundation_model(bundle_path, self.task_name)
        except Exception as e:
            raise InferenceError(f"Failed to load model: {e}")

        x = torch.tensor(self._arr[np.newaxis], dtype=torch.float32)  # (1, 129, 200)
        with torch.no_grad():
            out  = model(x, mode='finetune', task_name=self.task_name)
            pred = float(out['prediction'].squeeze().item())

        label, extra = self._format_prediction(pred, bundle)

        return {
            'success':           True,
            'prediction':        round(pred, 4),
            'prediction_label':  label,
            'prediction_proba':  None,
            'input_summary':     input_summary,
            'input_data': {
                'n_channels': 129,
                'n_samples':  200,
                'task':       self.task_name,
                **extra,
            },
        }

    def _format_prediction(self, pred: float, bundle: dict) -> tuple[str, dict]:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# Challenge 1 — Reaction Time
# ─────────────────────────────────────────────────────────────────────────────

@register("eeg_rt_predictor")
class EEGReactionTimeHandler(_EEGFoundationBase):
    """
    Predicts reaction time (ms) from a 2-second post-stimulus EEG window.
    Task: contrastChangeDetection (NeurIPS 2025 EEG Challenge 1).
    """
    task_name = 'rt'

    def _format_prediction(self, pred: float, bundle: dict):
        # pred is in z-score units (model trained on normalised RT)
        # convert to approximate ms using population stats from HBN-EEG
        # typical RT mean ~600ms, std ~150ms
        rt_ms = pred * 150 + 600
        label = f"{rt_ms:.0f} ms  (z={pred:+.2f})"
        extra = {
            'predicted_rt_ms':    round(rt_ms, 1),
            'predicted_rt_zscore': round(pred, 4),
            'best_val_nrmse':     round(bundle.get('best_val_nrmse', 0), 4),
            'interpretation':     (
                'Fast response' if rt_ms < 500
                else 'Average response' if rt_ms < 750
                else 'Slow response'
            ),
        }
        return label, extra


# ─────────────────────────────────────────────────────────────────────────────
# Challenge 2 — Externalizing Factor
# ─────────────────────────────────────────────────────────────────────────────

@register("eeg_externalizing_predictor")
class EEGExternalizingHandler(_EEGFoundationBase):
    """
    Predicts externalizing psychopathology factor from a 2-second EEG window.
    Task: NeurIPS 2025 EEG Challenge 2.
    Externalizing score: z-score relative to HBN population (mean=0, sd=1).
    Higher values indicate more externalizing symptoms (ADHD, conduct issues).
    """
    task_name = 'externalizing'

    def _format_prediction(self, pred: float, bundle: dict):
        if pred < -1.0:
            interp = "Well below average externalizing symptoms"
        elif pred < -0.5:
            interp = "Below average externalizing symptoms"
        elif pred < 0.5:
            interp = "Average range"
        elif pred < 1.0:
            interp = "Slightly elevated externalizing symptoms"
        else:
            interp = "Elevated externalizing symptoms"

        label = f"Score: {pred:+.3f}  ({interp})"
        extra = {
            'predicted_externalizing_zscore': round(pred, 4),
            'best_val_subj_nrmse':            round(bundle.get('best_val_subj_nrmse', 0), 4),
            'interpretation':                 interp,
            'note':                           (
                'This is a research model trained on a mini dataset (~220 subjects). '
                'Clinical use requires the full 3000+ subject training.'
            ),
        }
        return label, extra
