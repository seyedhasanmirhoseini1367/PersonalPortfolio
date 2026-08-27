import argparse
import os
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, roc_curve
from sklearn.preprocessing import LabelEncoder
from imblearn.over_sampling import SMOTE
from catboost import CatBoostClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

parser = argparse.ArgumentParser()
parser.add_argument("--data_path", type=str, required=True)
parser.add_argument("--output_path", type=str, default="./outputs")
args = parser.parse_args()

os.makedirs(args.output_path, exist_ok=True)

df = pd.read_csv(os.path.join(args.data_path, "train.csv"))
df = df.drop(columns=['id'])

# SeniorCitizen is binary categorical, tenure is ordinal numeric (1-72 months)
df['SeniorCitizen'] = df['SeniorCitizen'].astype('object')

categorical_cols = df.select_dtypes(include=['object']).columns.tolist()
categorical_cols = [col for col in categorical_cols if col != 'Churn']

encoders = {}
for col in categorical_cols:
    encoders[col] = LabelEncoder()
    df[col] = encoders[col].fit_transform(df[col])

# Cast categorical cols to pandas category dtype — LightGBM uses this for native splits
for col in categorical_cols:
    df[col] = df[col].astype('category')

X = df.drop(columns=['Churn'])
target_encoder = LabelEncoder()
y = target_encoder.fit_transform(df['Churn'])  # No -> 0, Yes -> 1

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# SMOTE requires numeric — convert back to int for resampling, then restore category
X_train_num = X_train.copy()
X_test_num = X_test.copy()
for col in categorical_cols:
    X_train_num[col] = X_train_num[col].cat.codes
    X_test_num[col] = X_test_num[col].cat.codes

smote = SMOTE(random_state=42)
X_train_sm, y_train_sm = smote.fit_resample(X_train_num, y_train)
X_train_sm = pd.DataFrame(X_train_sm, columns=X_train.columns)
X_test_sm = pd.DataFrame(X_test_num, columns=X_test.columns)

# Restore category dtype after SMOTE
for col in categorical_cols:
    X_train_sm[col] = X_train_sm[col].astype(int).astype('category')
    X_test_sm[col] = X_test_sm[col].astype(int).astype('category')

neg, pos = (y_train == 0).sum(), (y_train == 1).sum()
scale_pos = neg / pos

cat_feature_indices = [X_train_sm.columns.get_loc(col) for col in categorical_cols]

catboost_model = CatBoostClassifier(
    iterations=1000,
    learning_rate=0.1,
    depth=6,
    eval_metric='AUC',
    auto_class_weights='Balanced',
    cat_features=cat_feature_indices,
    random_seed=42,
    verbose=False
)
catboost_model.fit(X_train_sm.astype(object), y_train_sm)
y_pred_catboost = catboost_model.predict(X_test_sm.astype(object))
print("CatBoost Classification Report:")
print(classification_report(y_test, y_pred_catboost))
print("CatBoost Confusion Matrix:")
print(confusion_matrix(y_test, y_pred_catboost))
fpr_catboost, tpr_catboost, _ = roc_curve(y_test, catboost_model.predict_proba(X_test_sm.astype(object))[:, 1])
catboost_model.save_model(os.path.join(args.output_path, "catboost_model.cbm"))

xgb_model = XGBClassifier(
    n_estimators=1000,
    learning_rate=0.1,
    max_depth=6,
    scale_pos_weight=scale_pos,
    eval_metric='auc',
    random_state=42,
    verbosity=0
)
X_train_xgb = X_train_sm.copy()
X_test_xgb = X_test_sm.copy()
for col in categorical_cols:
    X_train_xgb[col] = X_train_xgb[col].cat.codes
    X_test_xgb[col] = X_test_xgb[col].cat.codes
xgb_model.fit(X_train_xgb, y_train_sm)
y_pred_xgb = xgb_model.predict(X_test_xgb)
print("XGBoost Classification Report:")
print(classification_report(y_test, y_pred_xgb))
print("XGBoost Confusion Matrix:")
print(confusion_matrix(y_test, y_pred_xgb))
fpr_xgb, tpr_xgb, _ = roc_curve(y_test, xgb_model.predict_proba(X_test_xgb)[:, 1])
joblib.dump(xgb_model, os.path.join(args.output_path, "xgb_model.pkl"))

lgbm_model = LGBMClassifier(
    n_estimators=1000,
    learning_rate=0.1,
    max_depth=6,
    class_weight='balanced',
    random_state=42,
    verbose=-1
)
lgbm_model.fit(X_train_sm, y_train_sm)
y_pred_lgbm = lgbm_model.predict(X_test_sm)
print("LightGBM Classification Report:")
print(classification_report(y_test, y_pred_lgbm))
print("LightGBM Confusion Matrix:")
print(confusion_matrix(y_test, y_pred_lgbm))
fpr_lgbm, tpr_lgbm, _ = roc_curve(y_test, lgbm_model.predict_proba(X_test_sm)[:, 1])
joblib.dump(lgbm_model, os.path.join(args.output_path, "lgbm_model.pkl"))

joblib.dump(encoders, os.path.join(args.output_path, "encoders.pkl"))
joblib.dump(target_encoder, os.path.join(args.output_path, "target_encoder.pkl"))
joblib.dump(list(X_train_sm.columns), os.path.join(args.output_path, "feature_names.pkl"))
joblib.dump(categorical_cols, os.path.join(args.output_path, "categorical_features.pkl"))
print(f"All models and encoders saved to {args.output_path}")
