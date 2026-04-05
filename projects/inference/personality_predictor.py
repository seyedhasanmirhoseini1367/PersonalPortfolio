# projects/inference/personality_predictor.py
"""
Inference handler for "Predict the Introverts from the Extroverts".

Input:  CSV file with one or more rows.
        Required columns: Stage_fear, Drained_after_socializing,
        Time_spent_Alone, Social_event_attendance, Going_outside,
        Friends_circle_size, Post_frequency

Output: Per-row prediction — Introvert or Extrovert.
        When multiple rows are uploaded, the result shown is for the
        first row; full results are in input_data["all_predictions"].

Admin config (file_input_config):
{
  "handler":          "personality_predictor",
  "accepted_formats": ["csv"],
  "description":      "Upload a CSV with one or more rows of personality survey answers.",
  "label_map":        {"0": "Extrovert", "1": "Introvert"}
}

Training:
    Run the management command to train and auto-save:
        python manage.py train_personality_model --project-id <id>
"""

import os
import pickle
import logging
import warnings

import numpy as np
import pandas as pd

from .base import InferenceHandler, InferenceError
from .registry import register

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


# ── Feature engineering  (must be identical to training code) ────────────────

def _create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror of create_features() in the training script."""
    df = df.copy()

    if 'Social_event_attendance' in df.columns and 'Time_spent_Alone' in df.columns:
        df['social_alone_ratio'] = df['Social_event_attendance'] / (df['Time_spent_Alone'] + 1)
        df['social_alone_diff']  = df['Social_event_attendance'] - df['Time_spent_Alone']

    if 'Social_event_attendance' in df.columns and 'Drained_after_socializing' in df.columns:
        df['social_battery'] = df['Social_event_attendance'] * df['Drained_after_socializing']

    if 'Friends_circle_size' in df.columns and 'Social_event_attendance' in df.columns:
        df['friend_social_interaction'] = df['Friends_circle_size'] * df['Social_event_attendance']

    if 'Going_outside' in df.columns and 'Post_frequency' in df.columns:
        df['outdoor_digital_balance'] = df['Going_outside'] - df['Post_frequency']

    numerical_cols = [c for c in ['Time_spent_Alone', 'Social_event_attendance',
                                   'Going_outside', 'Friends_circle_size', 'Post_frequency']
                      if c in df.columns]
    for i, c1 in enumerate(numerical_cols):
        for c2 in numerical_cols[i + 1:]:
            df[f'{c1}_{c2}_interaction'] = df[c1] * df[c2]

    for col in ['Social_event_attendance', 'Time_spent_Alone', 'Going_outside']:
        if col in df.columns:
            df[f'{col}_squared'] = df[col] ** 2

    return df


# ── Handler ───────────────────────────────────────────────────────────────────

@register("personality_predictor")
class PersonalityPredictorHandler(InferenceHandler):

    accepted_extensions = ["csv"]

    REQUIRED_COLUMNS = [
        'Stage_fear', 'Drained_after_socializing', 'Time_spent_Alone',
        'Social_event_attendance', 'Going_outside', 'Friends_circle_size',
        'Post_frequency',
    ]

    DEFAULT_LABEL_MAP = {"0": "Extrovert", "1": "Introvert"}

    # ── Base contract ─────────────────────────────────────────────────────────

    def validate_file(self, file, filename: str) -> None:
        """Check extension and file size."""
        super().validate_file(file, filename)          # checks extension
        if hasattr(file, 'size') and file.size > 50 * 1024 * 1024:
            raise InferenceError("File too large (max 50 MB).")

    def load_and_preprocess(self, file, filename: str):
        """
        Read CSV → validate columns → encode categoricals →
        engineer features → align to trained feature list.
        Returns (feature_df, input_summary).
        """
        # ── 1. Parse ──────────────────────────────────────────────────────────
        df = self.read_csv(file)

        # ── 2. Case-insensitive column normalisation ──────────────────────────
        rename = {c: c for c in df.columns}
        lower_map = {c.lower(): c for c in self.REQUIRED_COLUMNS}
        for col in df.columns:
            if col.lower() in lower_map:
                rename[col] = lower_map[col.lower()]
        df = df.rename(columns=rename)

        # ── 3. Validate required columns ──────────────────────────────────────
        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise InferenceError(
                f"Missing required columns: {missing}. "
                f"Your file has: {list(df.columns)}. "
                f"Required: {self.REQUIRED_COLUMNS}"
            )

        n_rows = len(df)
        if n_rows == 0:
            raise InferenceError("The uploaded CSV has no data rows.")

        # ── 4. Encode categorical columns using saved LabelEncoders ──────────
        #      Falls back to alphabetical encoding if encoders not saved.
        label_encoders = self._load_label_encoders()
        cat_cols = ['Stage_fear', 'Drained_after_socializing']

        for col in cat_cols:
            if col not in df.columns:
                continue
            if label_encoders and col in label_encoders:
                le = label_encoders[col]
                # Handle unseen values gracefully
                known = set(le.classes_)
                df[col] = df[col].apply(
                    lambda v: le.transform([v])[0] if v in known
                    else int(le.transform([le.classes_[0]])[0])
                )
            else:
                # Fallback: alphabetical LabelEncoder behaviour
                unique_vals = sorted(df[col].dropna().unique())
                mapping = {v: i for i, v in enumerate(unique_vals)}
                df[col] = df[col].map(mapping).fillna(0).astype(int)

        # ── 5. Fill NaN ───────────────────────────────────────────────────────
        df = df.fillna(df.median(numeric_only=True))

        # ── 6. Feature engineering (identical to training) ────────────────────
        df = _create_features(df)

        # ── 7. Align to training feature order ────────────────────────────────
        feature_names = self._load_feature_names()
        if feature_names:
            for col in feature_names:
                if col not in df.columns:
                    df[col] = 0        # add missing engineered features
            df = df[feature_names]     # enforce exact column order

        input_summary = {
            "format":           "CSV",
            "rows_uploaded":    n_rows,
            "columns":          list(df.columns[:8]),   # first 8 for display
            "note": f"Predicting row 1 of {n_rows}. Full results in details."
                    if n_rows > 1 else "Single row prediction.",
        }

        # Store all rows; base.run() will use first row — we surface the rest
        # via postprocess → input_data["all_predictions"]
        self._all_rows_df = df          # stash for postprocess
        self._n_rows      = n_rows
        return df, input_summary

    def postprocess(self, raw_prediction, proba: float | None,
                    feature_df: pd.DataFrame) -> dict:
        """
        raw_prediction and proba come from base.run() for the FIRST row.
        We also run the full multi-row prediction here and attach it.
        """
        label_map = {**self.DEFAULT_LABEL_MAP, **self.cfg.get("label_map", {})}
        pred_val  = int(raw_prediction[0]) if hasattr(raw_prediction[0], '__float__') \
                    else raw_prediction[0]
        label     = label_map.get(str(pred_val), str(pred_val))

        # Multi-row predictions (only meaningful if > 1 row)
        all_preds = None
        if hasattr(self, '_all_rows_df') and self._n_rows > 1:
            try:
                model = self._load_model()
                preds  = model.predict(self._all_rows_df)
                probas = model.predict_proba(self._all_rows_df) \
                         if hasattr(model, 'predict_proba') else None
                all_preds = []
                for i, p in enumerate(preds):
                    row = {
                        "row":        i + 1,
                        "prediction": label_map.get(str(int(p)), str(int(p))),
                        "confidence": round(float(max(probas[i])), 4) if probas is not None else None,
                    }
                    all_preds.append(row)
            except Exception:
                pass

        return {
            "prediction":       pred_val,
            "prediction_label": label,
            "prediction_proba": proba,
            "all_predictions":  all_preds,   # None for single-row uploads
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _model_base_path(self) -> str:
        """Return the path prefix used for all saved artefacts."""
        model_path = self.project.get_model_path()
        if not model_path:
            return ""
        return os.path.splitext(model_path)[0]

    def _load_label_encoders(self) -> dict | None:
        base = self._model_base_path()
        if not base:
            return None
        path = f"{base}_label_encoders.pkl"
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return None

    def _load_feature_names(self) -> list | None:
        base = self._model_base_path()
        if not base:
            return None
        path = f"{base}_feature_names.pkl"
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return None
