# Admin config reference — file_input_config per project

Copy-paste the JSON below into the project's `file_input_config` field in Django admin.

---

## Customer Churn Prediction

```json
{
  "handler": "customer_churn_predictor",
  "accepted_formats": ["csv"],
  "description": "Upload a CSV with one row of customer data to predict churn. Required columns: gender, SeniorCitizen, Partner, Dependents, tenure, PhoneService, MultipleLines, InternetService, OnlineSecurity, OnlineBackup, DeviceProtection, TechSupport, StreamingTV, StreamingMovies, Contract, PaperlessBilling, PaymentMethod, MonthlyCharges, TotalCharges."
}
```

**Artifacts required alongside the model file** (same directory, same base name):
- `<base>_encoders.pkl` — dict of LabelEncoders per categorical column
- `<base>_target_encoder.pkl` — LabelEncoder for target (No / Yes)
- `<base>_feature_names.pkl` — ordered list of feature column names

---

## Predicting Irrigation Need (CatBoost — Kaggle)

```json
{
  "handler": "irrigation_predictor",
  "accepted_formats": ["csv"],
  "description": "Upload a CSV with one row of field and weather measurements. Required columns: Soil_Type, Soil_pH, Soil_Moisture, Organic_Carbon, Electrical_Conductivity, Temperature_C, Humidity, Rainfall_mm, Sunlight_Hours, Wind_Speed_kmh, Crop_Type, Crop_Growth_Stage, Season, Irrigation_Type, Water_Source, Field_Area_hectare, Mulching_Used, Previous_Irrigation_mm, Region."
}
```

**Artifacts required alongside the model file** (same directory, same base name):
- `<base>_target_encoder.pkl` — LabelEncoder for the target (High / Low / Medium)
- `<base>_label_encoders.pkl` — empty dict `{}` (CatBoost handles categoricals natively)
- `<base>_feature_names.pkl` — ordered list of 19 feature column names
- `<base>_categorical_features.pkl` — list of categorical column names

All five files are in `d:/ml_project/irrigation_artifacts/` — upload them as a group.

---

## Seizure EEG Detection (thesis)

```json
{
  "handler": "seizure_eeg",
  "accepted_formats": ["parquet", "csv"],
  "description": "Upload a raw EEG segment as Parquet or CSV. The file must contain one column per EEG channel with time-series samples as rows. A 1-second segment at 256 Hz = 256 rows.",
  "sampling_rate_hz": 256,
  "expected_channels": [
    "Fp1","Fp2","F3","F4","C3","C4","P3","P4",
    "O1","O2","F7","F8","T3","T4","T5","T6",
    "Fz","Cz","Pz","A1","A2","T1","T2"
  ],
  "expected_n_features": 115,
  "label_map": {
    "0": "No seizure detected",
    "1": "Seizure activity detected"
  }
}
```

**What the handler does:**
Reads the EEG channels → computes Welch bandpower in 5 bands (delta, theta,
alpha, beta, gamma) per channel → produces 23 channels × 5 bands = 115 features
→ feeds the trained classifier.

**Adjust `expected_channels` and `expected_n_features` to match your actual training data.**

---

## Image classifier (skin lesion / X-ray / etc.)

```json
{
  "handler": "image_classifier",
  "accepted_formats": ["jpg", "jpeg", "png"],
  "description": "Upload a skin lesion photo (JPG or PNG). Minimum 224×224 pixels recommended.",
  "target_size": [224, 224],
  "normalize_mean": [0.485, 0.456, 0.406],
  "normalize_std":  [0.229, 0.224, 0.225],
  "label_map": {
    "0": "Benign",
    "1": "Malignant — consult a dermatologist"
  }
}
```

---

## Tabular / CSV project (diabetes, house price, etc.)

```json
{
  "handler": "tabular_passthrough",
  "accepted_formats": ["csv"],
  "description": "Upload a CSV with one row of data. All columns must be numeric.",
  "expected_columns": ["age", "bmi", "glucose", "insulin", "blood_pressure", "skin_thickness"],
  "expected_n_features": 6,
  "label_map": {
    "0": "No diabetes predicted",
    "1": "Diabetes risk detected"
  }
}
```

---

## Common fields (all handlers)

| Field | Required | Description |
|---|---|---|
| `handler` | **Yes** | Slug matching `@register("...")` in the handler file |
| `accepted_formats` | Yes | List of extensions shown in UI and used for validation |
| `description` | Yes | Shown above the drop zone on the demo page |
| `label_map` | Recommended | Maps raw model output (as string) to human label |
| `expected_n_features` | Recommended | Triggers clear error if feature count mismatches |
| `sampling_rate_hz` | EEG only | Used by bandpower extractor |
| `expected_channels` | EEG only | Channel names; triggers clear error if missing |
| `expected_columns` | Tabular only | Column names; triggers clear error if missing |
| `target_size` | Image only | Resize target as [w, h] |
| `normalize_mean/std` | Image only | Per-channel normalization values |
