# projects/inference/customer_churn_predictor.py
"""
Inference handler for "Customer Churn Prediction".

Input:  CSV file with one row of customer data.
        Required columns are loaded from the saved feature_names artifact.

Output: Churn prediction (Yes / No) with confidence score.

Admin config (file_input_config):
{
  "handler":          "customer_churn_predictor",
  "accepted_formats": ["csv"],
  "description":      "Upload a CSV with one row of customer data to predict churn."
}

Artifacts expected alongside the model .pkl file:
  <model_base>_encoders.pkl
  <model_base>_target_encoder.pkl
  <model_base>_feature_names.pkl
"""

import os
import pickle
import logging
import warnings

import pandas as pd

from .base import InferenceHandler, InferenceError
from .registry import register
from .azure_ml_client import AzureMLClient

warnings.filterwarnings('ignore')
logger = logging.getLogger(__name__)


@register("customer_churn_predictor")
class CustomerChurnPredictorHandler(InferenceHandler):

    accepted_extensions = ["csv"]

    use_azure_ml = True

    # ── Azure ML override ─────────────────────────────────────────────────────

    def run(self, uploaded_file) -> dict:
        """Try Azure ML first; fall back to local model pipeline."""
        if self.use_azure_ml:
            try:
                result = self._run_azure_ml(uploaded_file)
                if result is not None:
                    logger.info("customer_churn_predictor: used Azure ML endpoint.")
                    return result
                logger.info("customer_churn_predictor: Azure ML unavailable, using local model.")
            except Exception as exc:
                logger.warning("customer_churn_predictor: Azure ML error (%s), using local model.", exc)
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)

        return super().run(uploaded_file)

    def _run_azure_ml(self, uploaded_file) -> dict | None:
        """Call Azure ML endpoint. Returns result dict or None."""
        client = AzureMLClient()
        if not client.is_configured:
            return None

        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(0)
        df = self.read_csv(uploaded_file)
        payload = {"data": df.to_dict(orient="records")}

        response = client.predict(payload)
        if response is None:
            return None

        return {
            "success":          True,
            "prediction":       response.get("prediction"),
            "prediction_label": response.get("prediction_label", str(response.get("prediction", ""))),
            "prediction_proba": response.get("confidence"),
            "input_summary":    {"format": "CSV", "rows": len(df), "source": "azure_ml"},
            "input_data":       df.iloc[0].to_dict() if len(df) > 0 else {},
        }

    # ── Base contract ─────────────────────────────────────────────────────────

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)
        if hasattr(file, 'size') and file.size > 20 * 1024 * 1024:
            raise InferenceError("File too large (max 20 MB).")

    def load_and_preprocess(self, file, filename: str):
        df = self.read_csv(file)

        if len(df) == 0:
            raise InferenceError("The uploaded CSV has no data rows.")

        feature_names = self._load_artifact("feature_names")
        encoders = self._load_artifact("encoders") or {}

        if feature_names:
            missing = [c for c in feature_names if c not in df.columns]
            if missing:
                raise InferenceError(
                    f"Missing columns: {missing}. "
                    f"Your file has: {list(df.columns)}."
                )

        # SeniorCitizen is binary categorical — cast to object for encoding
        if 'SeniorCitizen' in df.columns:
            df['SeniorCitizen'] = df['SeniorCitizen'].astype(object)

        # Encode categorical columns using saved encoders
        for col, le in encoders.items():
            if col not in df.columns:
                continue
            known = set(le.classes_)
            df[col] = df[col].apply(
                lambda v: le.transform([str(v)])[0] if str(v) in known else 0
            )

        df = df.fillna(df.median(numeric_only=True))

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

        if target_encoder is not None:
            try:
                label = target_encoder.inverse_transform([int(pred_val)])[0]
            except Exception:
                label = str(pred_val)
        else:
            label = self.cfg.get("label_map", {}).get(str(pred_val), str(pred_val))

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
