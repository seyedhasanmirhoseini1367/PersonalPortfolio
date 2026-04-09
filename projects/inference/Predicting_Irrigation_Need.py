
import pickle
import joblib
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestRegressor
from catboost import CatBoostClassifier
import lightgbm as lgb
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier
from sklearn.metrics import balanced_accuracy_score, classification_report
import warnings
warnings.filterwarnings('ignore')

train_path = "D:\datasets\playground-series-s6\playground-series-s6e4/train.csv"
test_path = "D:\datasets\playground-series-s6\playground-series-s6e4/test.csv"
submission_path = "D:\datasets\playground-series-s6\playground-series-s6e4/sample_submission.csv"

# Load the dataset
train_df = pd.read_csv(train_path).drop(columns=["id"])
test_df = pd.read_csv(test_path).drop(columns=["id"])
submission_df = pd.read_csv(submission_path)

train_df.shape, test_df.shape

train_df.columns
train_df.info()

train_df['Irrigation_Need'].value_counts()

# Preprocess the data
X = train_df.drop(columns=["Irrigation_Need"])
y = train_df["Irrigation_Need"]

encoder = LabelEncoder()
y = encoder.fit_transform(y)

# Split the data into training and validation sets
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)


# Identify categorical columns (string columns)
categorical_features = X.select_dtypes(include=['object', 'str']).columns.tolist()
print(f"Categorical features: {categorical_features}")

# ==================== CATBOOST MODEL ====================
print("\n" + "="*50)
print("Training CatBoost Classifier...")
print("="*50)

catboost_model = CatBoostClassifier(
    random_state=42, 
    verbose=100,
    cat_features=categorical_features,
    loss_function='MultiClass',
    eval_metric='TotalF1',
    auto_class_weights='Balanced',
    early_stopping_rounds=50,
    iterations=1000
)

catboost_model.fit(X_train, y_train, eval_set=(X_val, y_val))

# Predict on validation set
y_pred_catboost = catboost_model.predict(X_val)
print("\nCatBoost Classification Report:")
print(classification_report(y_val, y_pred_catboost, target_names=encoder.classes_))
catboost_score = balanced_accuracy_score(y_val, y_pred_catboost)
print(f"CatBoost Balanced Accuracy Score: {catboost_score:.4f}")

# Save CatBoost model
catboost_path = "catboost_model.pkl"
with open(catboost_path, 'wb') as f:
    pickle.dump(catboost_model, f)
print(f"CatBoost model saved as {catboost_path}")


# ==================== LIGHTGBM MODEL (Fixed) ====================
print("\n" + "="*50)
print("Training LightGBM Classifier...")
print("="*50)

# Create copies
X_train_lgbm = X_train.copy()
X_val_lgbm = X_val.copy()
test_lgbm = test_df.copy()


# Apply Label Encoding (more reliable than category dtype)
label_encoders_lgb = {}
for col in categorical_features:
    le = LabelEncoder()
    X_train_lgbm[col] = le.fit_transform(X_train_lgbm[col])
    X_val_lgbm[col] = le.transform(X_val_lgbm[col])
    test_lgbm[col] = le.transform(test_lgbm[col])
    label_encoders_lgb[col] = le

num_classes = len(encoder.classes_)

lgbm_model = LGBMClassifier(
    random_state=42,
    n_estimators=300,
    learning_rate=0.1,
    max_depth=8,
    num_leaves=31,
    subsample=0.8,
    colsample_bytree=0.8,
    class_weight='balanced',
    objective='multiclass',  # num_class is inferred automatically from data
    n_jobs=-1,
    verbose=-1  # suppress default warnings; logging handled by callback below
)

lgbm_model.fit(
    X_train_lgbm, y_train,
    eval_set=[(X_val_lgbm, y_val)],
    callbacks=[lgb.log_evaluation(period=100)]  # print eval every 100 rounds
)

# Predict on validation set
y_pred_lgbm = lgbm_model.predict(X_val_lgbm)
print("\nLightGBM Classification Report:")
print(classification_report(y_val, y_pred_lgbm, target_names=encoder.classes_))
lgbm_score = balanced_accuracy_score(y_val, y_pred_lgbm)
print(f"LightGBM Balanced Accuracy Score: {lgbm_score:.4f}")

# Save model
lgbm_path = "lightgbm_model.pkl"
with open(lgbm_path, 'wb') as f:
    pickle.dump(lgbm_model, f)
print(f"LightGBM model saved as {lgbm_path}")

# ==================== XGBOOST MODEL ====================
print("\n" + "="*50)
print("Training XGBoost Classifier...")
print("="*50)

# For XGBoost, we need to encode categorical features
from sklearn.preprocessing import LabelEncoder

# Create a copy for XGBoost
X_train_xgb = X_train.copy()
X_val_xgb = X_val.copy()
test_xgb = test_df.copy()  # id already dropped at load time

# Encode categorical features for XGBoost
label_encoders = {}
for col in categorical_features:
    le = LabelEncoder()
    # Fit on combined data to handle all possible categories
    combined = pd.concat([X_train_xgb[col], X_val_xgb[col], test_xgb[col]]).astype(str)
    le.fit(combined)
    X_train_xgb[col] = le.transform(X_train_xgb[col].astype(str))
    X_val_xgb[col] = le.transform(X_val_xgb[col].astype(str))
    test_xgb[col] = le.transform(test_xgb[col].astype(str))
    label_encoders[col] = le

xgb_model = XGBClassifier(
    random_state=42,
    n_estimators=1000,
    learning_rate=0.1,
    max_depth=10,
    subsample=0.8,
    colsample_bytree=0.8,
    objective='multi:softmax',  # Multiclass classification
    num_class=len(encoder.classes_),  # Number of classes
    eval_metric='mlogloss',  # Multiclass log loss
    early_stopping_rounds=50,
    use_label_encoder=False,
    verbosity=1
)

xgb_model.fit(
    X_train_xgb, y_train,
    eval_set=[(X_val_xgb, y_val)],
    verbose=100
)

# Predict on validation set
y_pred_xgb = xgb_model.predict(X_val_xgb)
print("\nXGBoost Classification Report:")
print(classification_report(y_val, y_pred_xgb, target_names=encoder.classes_))
xgb_score = balanced_accuracy_score(y_val, y_pred_xgb)
print(f"XGBoost Balanced Accuracy Score: {xgb_score:.4f}")

# Save XGBoost model
xgb_path = "xgboost_model.pkl"
with open(xgb_path, 'wb') as f:
    pickle.dump(xgb_model, f)
print(f"XGBoost model saved as {xgb_path}")

# ==================== MODEL COMPARISON ====================
print("\n" + "="*50)
print("Model Performance Summary")
print("="*50)
print(f"CatBoost Balanced Accuracy: {catboost_score:.4f}")
print(f"LightGBM Balanced Accuracy: {lgbm_score:.4f}")
print(f"XGBoost Balanced Accuracy: {xgb_score:.4f}")

# Choose the best model based on balanced accuracy
scores = {
    'CatBoost': catboost_score,
    'LightGBM': lgbm_score,
    'XGBoost': xgb_score
}
best_model_name = max(scores, key=scores.get)
best_model = eval(f"{best_model_name.lower()}_model")
print(f"\nBest model: {best_model_name} with score {scores[best_model_name]:.4f}")

# ==================== PREDICT ON TEST SET ====================
print("\n" + "="*50)
print("Making predictions on test set...")
print("="*50)

# Prepare test data based on the best model
if best_model_name == 'CatBoost':
    test_predictions = best_model.predict(test_df)  # id already dropped
elif best_model_name == 'LightGBM':
    test_lgbm_final = test_df.copy()
    for col in categorical_features:
        test_lgbm_final[col] = label_encoders_lgb[col].transform(test_lgbm_final[col])
    test_predictions = best_model.predict(test_lgbm_final)
else:  # XGBoost
    # Prepare test data for XGBoost
    test_xgb = test_df.drop(columns=["id"]).copy()
    for col in categorical_features:
        test_xgb[col] = label_encoders[col].transform(test_xgb[col].astype(str))
    test_predictions = best_model.predict(test_xgb)

# Convert predictions back to original labels
test_predictions_labels = encoder.inverse_transform(test_predictions)

# Prepare the submission file
submission_df = pd.read_csv(submission_path)  # reload to get original ids
submission_df = pd.DataFrame()
submission_df["id"] = pd.read_csv(test_path)["id"]
submission_df["Irrigation_Need"] = test_predictions_labels
submission_df.to_csv("D:\datasets\playground-series-s6\playground-series-s6e4/submission.csv", index=False)
print("\nSubmission file saved as 'submission.csv'")
print(f"Using {best_model_name} as the final model")

# Also save the best model separately
best_model_path = f"D:\datasets\playground-series-s6\playground-series-s6e4/best_model_{best_model_name.lower()}.pkl"
with open(best_model_path, 'wb') as f:
    pickle.dump(best_model, f)
print(f"Best model saved as {best_model_path}")

# ── Save artifacts needed by the Django inference handler ─────────────────────
import os
artifact_base = os.path.splitext(best_model_path)[0]

with open(f"{artifact_base}_target_encoder.pkl", 'wb') as f:
    pickle.dump(encoder, f)

with open(f"{artifact_base}_label_encoders.pkl", 'wb') as f:
    pickle.dump(label_encoders, f)

with open(f"{artifact_base}_feature_names.pkl", 'wb') as f:
    pickle.dump(list(X_train.columns), f)

with open(f"{artifact_base}_categorical_features.pkl", 'wb') as f:
    pickle.dump(categorical_features, f)

with open(f"{artifact_base}_model_type.pkl", 'wb') as f:
    pickle.dump(best_model_name, f)

print(f"\nAll artifacts saved with prefix: {artifact_base}")
print(f"Best model saved as {best_model_path}")