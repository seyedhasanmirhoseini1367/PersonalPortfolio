# projects/inference/tabular_passthrough.py
"""
Generic tabular handler — CSV or Parquet where columns map directly to model features.
No feature engineering; columns are used as-is in the order the model expects.

Config example:
{
  "handler": "tabular_passthrough",
  "accepted_formats": ["csv", "parquet"],
  "description": "Upload a CSV with one row of patient vitals.",
  "expected_columns": ["age","bmi","glucose","insulin","blood_pressure"],
  "label_map": {"0": "No diabetes", "1": "Diabetes predicted"}
}
"""

import pandas as pd
from .registry import register
from .base import InferenceHandler, InferenceError


@register("tabular_passthrough")
class TabularPassthroughHandler(InferenceHandler):

    accepted_extensions = ["csv", "parquet"]

    def load_and_preprocess(self, file, filename: str):
        df = self.read_parquet(file) if filename.endswith(".parquet") else self.read_csv(file)

        expected_cols = self.cfg.get("expected_columns")
        if expected_cols:
            missing = [c for c in expected_cols if c not in df.columns]
            if missing:
                raise InferenceError(
                    f"Your file is missing required columns: {missing}. "
                    f"Found: {list(df.columns)}. "
                    f"Required: {expected_cols}."
                )
            df = df[expected_cols]

        # Use first row only
        feature_df = df.iloc[[0]]

        # Check all values are numeric
        non_numeric = [c for c in feature_df.columns if not pd.api.types.is_numeric_dtype(feature_df[c])]
        if non_numeric:
            raise InferenceError(
                f"Non-numeric columns found: {non_numeric}. "
                "All feature columns must contain numeric values."
            )

        summary = {
            "format":   filename.rsplit(".", 1)[-1].upper(),
            "columns":  list(df.columns),
            "n_cols":   len(df.columns),
            "n_rows_in_file": len(df),
            "note":     "Using first row for prediction.",
        }
        return feature_df, summary
