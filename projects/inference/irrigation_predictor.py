# projects/inference/irrigation_predictor.py
"""
Inference handler for "Predicting Irrigation Need".

Input:  CSV file with one row of field/weather measurements.
        Required columns are loaded from the saved feature_names artifact.

Output: Irrigation need class (e.g. Low / Medium / High).

Admin config (file_input_config):
{
  "handler":          "irrigation_predictor",
  "accepted_formats": ["csv"],
  "description":      "Upload a CSV with one row of field and weather measurements."
}

Artifacts expected alongside the model .pkl file:
  <model_base>_target_encoder.pkl
  <model_base>_label_encoders.pkl
  <model_base>_feature_names.pkl
  <model_base>_categorical_features.pkl
  <model_base>_model_type.pkl
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


@register("irrigation_predictor")
class IrrigationPredictorHandler(InferenceHandler):

    accepted_extensions = ["csv"]

    # ── Base contract ─────────────────────────────────────────────────────────

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)
        if hasattr(file, 'size') and file.size > 20 * 1024 * 1024:
            raise InferenceError("File too large (max 20 MB).")

    def load_and_preprocess(self, file, filename: str):
        df = self.read_csv(file)

        if len(df) == 0:
            raise InferenceError("The uploaded CSV has no data rows.")

        feature_names       = self._load_artifact("feature_names")
        categorical_features = self._load_artifact("categorical_features") or []
        label_encoders      = self._load_artifact("label_encoders") or {}

        # Validate required columns
        if feature_names:
            missing = [c for c in feature_names if c not in df.columns]
            if missing:
                raise InferenceError(
                    f"Missing columns: {missing}. "
                    f"Your file has: {list(df.columns)}."
                )

        # Encode categorical columns
        for col in categorical_features:
            if col not in df.columns:
                continue
            if col in label_encoders:
                le = label_encoders[col]
                known = set(le.classes_)
                df[col] = df[col].apply(
                    lambda v: le.transform([str(v)])[0] if str(v) in known
                    else 0
                )
            else:
                unique_vals = sorted(df[col].dropna().astype(str).unique())
                mapping = {v: i for i, v in enumerate(unique_vals)}
                df[col] = df[col].astype(str).map(mapping).fillna(0).astype(int)

        # Fill missing values
        df = df.fillna(df.median(numeric_only=True))

        # Align to training feature order
        if feature_names:
            for col in feature_names:
                if col not in df.columns:
                    df[col] = 0
            df = df[feature_names]

        input_summary = {
            "format":  "CSV",
            "rows":    len(df),
            "columns": len(df.columns),
        }

        self._all_rows_df = df
        return df, input_summary

    def postprocess(self, raw_prediction, proba, feature_df):
        target_encoder = self._load_artifact("target_encoder")

        pred_val = raw_prediction[0]
        if hasattr(pred_val, 'item'):
            pred_val = pred_val.item()

        # Decode numeric prediction → original class label
        if target_encoder is not None:
            try:
                label = target_encoder.inverse_transform([int(pred_val)])[0]
            except Exception:
                label = str(pred_val)
        else:
            label = self.cfg.get("label_map", {}).get(str(pred_val), str(pred_val))

        # Multi-row predictions
        all_preds = None
        if hasattr(self, '_all_rows_df') and len(self._all_rows_df) > 1:
            try:
                model = self._load_model()
                preds = model.predict(self._all_rows_df)
                probas = model.predict_proba(self._all_rows_df) \
                         if hasattr(model, 'predict_proba') else None
                all_preds = []
                for i, p in enumerate(preds):
                    decoded = target_encoder.inverse_transform([int(p)])[0] \
                              if target_encoder else str(p)
                    all_preds.append({
                        "row":        i + 1,
                        "prediction": decoded,
                        "confidence": round(float(max(probas[i])), 4)
                                      if probas is not None else None,
                    })
            except Exception:
                pass

        return {
            "prediction":       pred_val,
            "prediction_label": label,
            "prediction_proba": proba,
            "all_predictions":  all_preds,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _artifact_base(self) -> str:
        model_path = self.project.get_model_path()
        if not model_path:
            return ""
        return os.path.splitext(model_path)[0]

    def _load_artifact(self, name: str):
        base = self._artifact_base()
        if not base:
            return None
        path = f"{base}_{name}.pkl"
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        logger.warning("Artifact not found: %s", path)
        return None
