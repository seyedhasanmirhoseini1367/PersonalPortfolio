# projects/inference/base.py
"""
Base class every inference handler must inherit from.

Contract
--------
Handler receives:
    - self.project  : the Projects model instance
    - self.cfg      : project.file_input_config dict

Handler must implement:
    validate_file(file)  -> None  (raise InferenceError on bad input)
    load_and_preprocess(file) -> (feature_df, input_summary_dict)
    postprocess(raw_prediction, proba, feature_df) -> dict

The run() method orchestrates all three steps and handles model loading.
Handlers never touch _load_model() — that lives in base.
"""

import os
import pickle
import numpy as np
import pandas as pd


class InferenceError(ValueError):
    """Raised when input validation or preprocessing fails.
    Message is shown directly to the user in the demo UI.
    """


class InferenceHandler:
    """Abstract base for all project-specific inference handlers."""

    # Subclasses declare which file extensions they accept.
    # Used for both UI hints and validate_file().
    accepted_extensions: list[str] = []

    def __init__(self, project):
        self.project = project
        self.cfg     = project.file_input_config or {}

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, uploaded_file) -> dict:
        """
        Full inference pipeline.
        Returns a dict ready to be sent as JsonResponse:
        {
            "success": True,
            "prediction": <raw value>,
            "prediction_label": <human label>,
            "prediction_proba": <float|None>,
            "input_summary": { ... },   # shown in UI
            "input_data": { ... },      # sent to RAG
        }
        """
        filename = uploaded_file.name.lower()

        # 1. Validate file format
        self.validate_file(uploaded_file, filename)

        # 2. Parse + preprocess → feature DataFrame
        feature_df, input_summary = self.load_and_preprocess(uploaded_file, filename)

        # 3. Validate feature shape matches model expectations
        self._validate_features(feature_df)

        # 4. Load model + predict
        model = self._load_model()
        raw_pred = model.predict(feature_df)

        proba = None
        if hasattr(model, "predict_proba"):
            try:
                proba_arr = model.predict_proba(feature_df)[0]
                proba = float(max(proba_arr))
            except Exception:
                pass

        # 5. Postprocess → final result dict
        result = self.postprocess(raw_pred, proba, feature_df)
        result["input_summary"] = input_summary
        result["input_data"]    = {
            k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in dict(zip(feature_df.columns, feature_df.iloc[0].tolist())).items()
        }
        result["success"] = True
        return result

    # ── Methods subclasses must implement ────────────────────────────────────

    def validate_file(self, file, filename: str) -> None:
        """
        Check extension and any format-specific rules.
        Raise InferenceError with a user-friendly message on failure.
        """
        if self.accepted_extensions:
            ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
            if ext not in self.accepted_extensions:
                raise InferenceError(
                    f'This project expects: {", ".join(self.accepted_extensions).upper()}. '
                    f'You uploaded a .{ext.upper()} file.'
                )

    def load_and_preprocess(self, file, filename: str):
        """
        Parse the file and return (feature_df, input_summary).
        Raise InferenceError on shape/column mismatch.
        """
        raise NotImplementedError("Subclass must implement load_and_preprocess()")

    def postprocess(self, raw_prediction, proba: float | None, feature_df: pd.DataFrame) -> dict:
        """
        Convert raw model output to a human-readable result dict.
        Default implementation works for most classifiers/regressors.
        Override for custom label logic.
        """
        label_map = self.cfg.get("label_map", {})
        pred_val  = raw_prediction[0]
        if hasattr(pred_val, "item"):
            pred_val = pred_val.item()

        label = label_map.get(str(int(pred_val) if isinstance(pred_val, float) and pred_val == int(pred_val) else pred_val),
                              str(pred_val))
        return {
            "prediction":       pred_val,
            "prediction_label": label,
            "prediction_proba": proba,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_model(self):
        path = self.project.get_model_path()
        if not path or not os.path.exists(path):
            raise InferenceError(
                "Model file not found on the server. "
                "Please contact the site owner to upload the trained model."
            )
        try:
            if path.endswith((".pkl", ".pickle")):
                with open(path, "rb") as f:
                    return pickle.load(f)
            if path.endswith(".joblib"):
                import joblib
                return joblib.load(path)
            if path.endswith(".h5") or path.endswith(".keras"):
                from tensorflow import keras
                return keras.models.load_model(path)
            if path.endswith(".pt") or path.endswith(".pth"):
                import torch
                return torch.load(path, map_location="cpu")
            raise InferenceError(
                f"Unsupported model file format: {os.path.basename(path)}. "
                "Supported: .pkl, .pickle, .joblib, .h5, .keras, .pt, .pth"
            )
        except InferenceError:
            raise
        except Exception as e:
            raise InferenceError(f"Failed to load model: {e}")

    def _validate_features(self, feature_df: pd.DataFrame) -> None:
        """
        If the config specifies expected_n_features, check the shape.
        Raises InferenceError with a clear mismatch message.
        """
        expected_n = self.cfg.get("expected_n_features")
        if expected_n is None:
            return
        actual_n = feature_df.shape[1]
        if actual_n != expected_n:
            raise InferenceError(
                f"Feature count mismatch: the model was trained on {expected_n} features, "
                f"but your file produced {actual_n} features after preprocessing. "
                f"Check that your file has the correct channels/columns."
            )

    # ── Shared parsing utilities (handlers may call these) ───────────────────

    @staticmethod
    def read_csv(file) -> pd.DataFrame:
        try:
            return pd.read_csv(file)
        except Exception as e:
            raise InferenceError(f"Could not read CSV: {e}")

    @staticmethod
    def read_parquet(file) -> pd.DataFrame:
        try:
            return pd.read_parquet(file)
        except ImportError:
            raise InferenceError("Parquet support requires pyarrow. Run: pip install pyarrow")
        except Exception as e:
            raise InferenceError(f"Could not read Parquet: {e}")

    @staticmethod
    def read_json(file) -> pd.DataFrame:
        import json
        try:
            raw = json.load(file)
        except Exception as e:
            raise InferenceError(f"Could not parse JSON: {e}")
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        if isinstance(raw, dict):
            if "data" in raw and "columns" in raw:
                return pd.DataFrame(raw["data"], columns=raw["columns"])
            return pd.DataFrame(raw)
        raise InferenceError("JSON must be an array of records or {data, columns} object.")

    @staticmethod
    def read_image(file, target_size: tuple | None = None) -> np.ndarray:
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(file.read()))
            if target_size:
                img = img.resize(target_size)
            return np.array(img)
        except ImportError:
            raise InferenceError("Image support requires Pillow. Run: pip install Pillow")
        except Exception as e:
            raise InferenceError(f"Could not read image: {e}")

    @staticmethod
    def read_edf(file) -> tuple[pd.DataFrame, dict]:
        import tempfile, shutil, os
        with tempfile.NamedTemporaryFile(suffix=".edf", delete=False) as tmp:
            shutil.copyfileobj(file, tmp)
            tmp_path = tmp.name
        try:
            try:
                import mne
                raw = mne.io.read_raw_edf(tmp_path, preload=True, verbose=False)
                data, _ = raw.get_data(return_times=True)
                df = pd.DataFrame(data.T, columns=raw.ch_names)
                summary = {
                    "format": "EDF", "channels": raw.ch_names,
                    "n_channels": len(raw.ch_names), "n_samples": data.shape[1],
                    "sampling_rate_hz": raw.info["sfreq"],
                    "duration_sec": round(data.shape[1] / raw.info["sfreq"], 2),
                }
                return df, summary
            except ImportError:
                pass
            try:
                import pyedflib
                f = pyedflib.EdfReader(tmp_path)
                n, ch = f.signals_in_file, f.getSignalLabels()
                data  = np.array([f.readSignal(i) for i in range(n)])
                f._close()
                df = pd.DataFrame(data.T, columns=ch)
                return df, {"format": "EDF", "channels": ch, "n_channels": n, "n_samples": data.shape[1]}
            except ImportError:
                pass
            raise InferenceError(
                "EDF reading requires mne or pyEDFlib. "
                "Run: pip install mne  OR  pip install pyEDFlib"
            )
        finally:
            os.unlink(tmp_path)
