# How to add a new inference handler

Every project that has a prediction demo needs one handler file.
This is the only file you write. The rest of the system (views, template,
RAG) picks it up automatically.

---

## 1. Create the handler file

Create `projects/inference/my_project.py`:

```python
import pandas as pd
from .registry import register
from .base import InferenceHandler, InferenceError

@register("my_project_slug")        # ← must match file_input_config["handler"] in admin
class MyProjectHandler(InferenceHandler):

    accepted_extensions = ["csv", "parquet"]   # shown in UI and validated

    def validate_file(self, file, filename: str) -> None:
        super().validate_file(file, filename)       # checks extension
        if hasattr(file, "size") and file.size > 20 * 1024 * 1024:
            raise InferenceError("File too large (max 20 MB).")

    def load_and_preprocess(self, file, filename: str):
        # 1. Parse
        df = self.read_parquet(file) if filename.endswith(".parquet") else self.read_csv(file)

        # 2. Validate columns
        required = self.cfg.get("expected_columns", [])
        missing  = [c for c in required if c not in df.columns]
        if missing:
            raise InferenceError(
                f"Missing columns: {missing}. "
                f"Your file has: {list(df.columns)[:10]}."
            )

        # 3. Feature engineering (whatever your model was trained on)
        feature_df = df[required].iloc[[0]]   # first row, correct column order

        summary = {
            "format":  filename.rsplit(".", 1)[-1].upper(),
            "rows":    len(df),
            "columns": len(df.columns),
        }
        return feature_df, summary

    def postprocess(self, raw_prediction, proba, feature_df):
        label_map = self.cfg.get("label_map", {})
        pred_val  = raw_prediction[0]
        if hasattr(pred_val, "item"):
            pred_val = pred_val.item()
        label = label_map.get(str(pred_val), str(pred_val))
        return {
            "prediction":       pred_val,
            "prediction_label": label,
            "prediction_proba": proba,
        }
```

**Rules for `InferenceError`:**
- Raise it for anything the user caused: wrong format, missing columns,
  file too large, too few samples, wrong shape.
- It is shown word-for-word in the demo UI.
- Do NOT raise it for server errors (missing model file, library crash) —
  let those bubble up as regular exceptions so they log to the server.

---

## 2. Register the import in views.py

Open `projects/views.py` and add one line in the import block:

```python
import projects.inference.my_project     # noqa: F401
```

This makes the `@register(...)` decorator run at startup.

---

## 3. Configure the project in Django admin

Go to `/admin/projects/projects/` → your project → **file_input_config**:

```json
{
  "handler":           "my_project_slug",
  "accepted_formats":  ["csv", "parquet"],
  "description":       "Upload a CSV with one row of patient vitals.",
  "expected_columns":  ["age", "bmi", "glucose", "blood_pressure"],
  "expected_n_features": 4,
  "label_map":         {"0": "Negative", "1": "Positive"},
  "sampling_rate_hz":  256
}
```

Also set:
- `prediction_input_type` → **file**
- `prediction_endpoint` → **✓ checked**
- `trained_model` → upload your `.pkl` / `.joblib` / `.h5` file

---

## 4. Validate locally before pushing to Azure

```bash
# Quick smoke-test: does the handler resolve?
python manage.py shell -c "
from projects.models import Projects
from projects.inference import get_handler
p = Projects.objects.get(title='Your Project Title')
h = get_handler(p)
print(type(h).__name__, h.accepted_extensions)
"
```

---

## Available built-in parsers (call from load_and_preprocess)

| Method | Use for |
|---|---|
| `self.read_csv(file)` | CSV |
| `self.read_parquet(file)` | Parquet (requires pyarrow) |
| `self.read_json(file)` | JSON array or {data, columns} |
| `self.read_image(file, target_size=(224,224))` | PNG, JPG → np.ndarray |
| `self.read_edf(file)` | EDF brain signals (requires mne or pyedflib) |

---

## Azure deployment checklist

When you deploy a new project to Azure:

1. Upload the trained model file via Django admin (or copy to
   `media/projects/models/` in your Azure storage mount).
2. Deploy the new handler `.py` file — it's just a Python file, no
   migrations needed.
3. Add the import line to `views.py` and redeploy the app service.
4. Set `file_input_config["handler"]` in the Azure production admin.
5. Set environment variables: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
   in Azure App Service → Configuration → Application settings.

---

## Handler registry at a glance

| Slug | File | Project |
|---|---|---|
| `seizure_eeg` | `seizure_eeg.py` | EEG Seizure Detection (thesis) |
| `image_classifier` | `image_classifier.py` | Any CNN image classifier |
| `tabular_passthrough` | `tabular_passthrough.py` | Any plain CSV/Parquet project |
| *(add yours here)* | | |
