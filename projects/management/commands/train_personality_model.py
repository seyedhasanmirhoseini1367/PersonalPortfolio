# projects/management/commands/train_personality_model.py
"""
Train the personality predictor ensemble and save artefacts directly
into the project's media folder, then update the Django DB record.

Usage:
    python manage.py train_personality_model --project-id 2
    python manage.py train_personality_model --project-id 2 --trials 30
    python manage.py train_personality_model --project-id 2 --data-dir D:/datasets/playground-series-s5e7

What it saves (all in media/projects/models/):
    personality_<id>.pkl                  ← the trained ensemble (pickle)
    personality_<id>_label_encoders.pkl   ← LabelEncoder per categorical col
    personality_<id>_feature_names.pkl    ← ordered list of feature names
"""

import os
import pickle
import warnings
warnings.filterwarnings('ignore')

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Train the personality predictor and auto-save to the project record'

    def add_arguments(self, parser):
        parser.add_argument(
            '--project-id', type=int, required=True,
            help='ID of the Projects record to attach the trained model to',
        )
        parser.add_argument(
            '--data-dir', type=str,
            default=None,
            help='Folder containing train.csv, test.csv, sample_submission.csv '
                 'and optionally personality_dataset.csv. '
                 'Default: reads DATA_DIR from Django settings.',
        )
        parser.add_argument(
            '--trials', type=int, default=30,
            help='Optuna hyperparameter search trials (default: 30)',
        )
        parser.add_argument(
            '--skip-optuna', action='store_true',
            help='Skip hyperparameter tuning and use sensible defaults',
        )

    def handle(self, *args, **options):
        project_id = options['project_id']
        trials     = options['trials']
        skip_optuna = options['skip_optuna']

        # ── Resolve data directory ────────────────────────────────────────────
        data_dir = options['data_dir'] or getattr(settings, 'PERSONALITY_DATA_DIR', None)
        if not data_dir:
            raise CommandError(
                'Provide --data-dir or set PERSONALITY_DATA_DIR in settings.py.\n'
                'Example: PERSONALITY_DATA_DIR = "D:/datasets/playground-series-s5e7"'
            )
        if not os.path.isdir(data_dir):
            raise CommandError(f'Data directory not found: {data_dir}')

        # ── Load project record ───────────────────────────────────────────────
        from projects.models import Projects
        try:
            project = Projects.objects.get(pk=project_id)
        except Projects.DoesNotExist:
            raise CommandError(f'No project found with id={project_id}')

        self.stdout.write(f'\nTraining model for project: "{project.title}" (id={project_id})')
        self.stdout.write(f'Data directory: {data_dir}')

        # ── Import training dependencies ──────────────────────────────────────
        try:
            import numpy as np
            import pandas as pd
            from sklearn.preprocessing import LabelEncoder
            from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
            from sklearn.metrics import accuracy_score
            from sklearn.ensemble import RandomForestClassifier
            import lightgbm as lgb
            from catboost import CatBoostClassifier
        except ImportError as e:
            raise CommandError(
                f'Missing training dependency: {e}. '
                'Run: pip install catboost lightgbm scikit-learn pandas numpy'
            )

        # ── Load data ─────────────────────────────────────────────────────────
        self.stdout.write('\nLoading data...')
        train_path = os.path.join(data_dir, 'train.csv')
        extra_path = os.path.join(data_dir, 'personality_dataset.csv')

        if not os.path.exists(train_path):
            raise CommandError(f'train.csv not found in {data_dir}')

        train = pd.read_csv(train_path)
        if 'id' in train.columns:
            train = train.drop('id', axis=1)
        train = train.dropna(axis=0)

        # Optionally merge extra dataset
        if os.path.exists(extra_path):
            extra = pd.read_csv(extra_path).dropna(axis=0)
            train = pd.concat([train, extra], axis=0).reset_index(drop=True)
            self.stdout.write(f'  Combined dataset shape: {train.shape}')
        else:
            self.stdout.write(f'  Train dataset shape: {train.shape}')

        # ── Preprocess ────────────────────────────────────────────────────────
        self.stdout.write('\nPreprocessing...')
        X, y, label_encoders = self._preprocess(train)

        # ── Feature engineering ───────────────────────────────────────────────
        self.stdout.write('Engineering features...')
        X = self._create_features(X)
        feature_names = list(X.columns)
        self.stdout.write(f'  {len(feature_names)} features')

        # ── Train / validation split ──────────────────────────────────────────
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        # ── Optuna (optional) ─────────────────────────────────────────────────
        cat_params = self._default_catboost_params()
        if not skip_optuna:
            try:
                import optuna
                optuna.logging.set_verbosity(optuna.logging.WARNING)
                self.stdout.write(f'\nRunning Optuna hyperparameter search ({trials} trials)...')
                cat_params = self._optimize_catboost(X_train, y_train, X_val, y_val, trials)
                self.stdout.write(f'  Best params found: {cat_params}')
            except ImportError:
                self.stdout.write(self.style.WARNING(
                    '  optuna not installed — using defaults. '
                    'Run: pip install optuna'
                ))

        # ── Train ensemble ────────────────────────────────────────────────────
        self.stdout.write('\nTraining ensemble...')
        models = self._train_ensemble(X_train, y_train, X_val, y_val, cat_params)

        # ── Evaluate ──────────────────────────────────────────────────────────
        weights = {'catboost': 0.5, 'lightgbm': 0.3, 'random_forest': 0.2}
        val_acc = self._ensemble_accuracy(models, weights, X_val, y_val)
        self.stdout.write(self.style.SUCCESS(
            f'\nEnsemble validation accuracy: {val_acc:.4f} ({val_acc*100:.2f}%)'
        ))

        # ── Save artefacts ────────────────────────────────────────────────────
        media_root  = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
        model_dir   = os.path.join(media_root, 'projects', 'models')
        os.makedirs(model_dir, exist_ok=True)

        model_filename    = f'personality_{project_id}.pkl'
        encoders_filename = f'personality_{project_id}_label_encoders.pkl'
        features_filename = f'personality_{project_id}_feature_names.pkl'

        model_abs    = os.path.join(model_dir, model_filename)
        encoders_abs = os.path.join(model_dir, encoders_filename)
        features_abs = os.path.join(model_dir, features_filename)

        # Save the ensemble wrapper
        with open(model_abs, 'wb') as f:
            pickle.dump(_EnsembleWrapper(models, weights), f)
        self.stdout.write(f'  Saved model       → {model_abs}')

        with open(encoders_abs, 'wb') as f:
            pickle.dump(label_encoders, f)
        self.stdout.write(f'  Saved encoders    → {encoders_abs}')

        with open(features_abs, 'wb') as f:
            pickle.dump(feature_names, f)
        self.stdout.write(f'  Saved feature list→ {features_abs}')

        # ── Update Django DB record ───────────────────────────────────────────
        rel_path = os.path.join('projects', 'models', model_filename)
        project.trained_model = rel_path
        project.accuracy_score = round(val_acc * 100, 2)
        project.prediction_endpoint = True
        project.prediction_input_type = 'file'
        project.save(update_fields=[
            'trained_model', 'accuracy_score',
            'prediction_endpoint', 'prediction_input_type',
        ])
        self.stdout.write(self.style.SUCCESS(
            f'\n✔ Project record updated: trained_model="{rel_path}", '
            f'accuracy={project.accuracy_score}%, prediction_endpoint=True'
        ))
        self.stdout.write(
            '\nNext step: make sure file_input_config in admin is set to:\n'
            '  {"handler": "personality_predictor", '
            '"accepted_formats": ["csv"], '
            '"description": "Upload a CSV with personality survey answers.", '
            '"label_map": {"0": "Extrovert", "1": "Introvert"}}'
        )

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _preprocess(self, df):
        import pandas as pd
        from sklearn.preprocessing import LabelEncoder

        X = df.drop('Personality', axis=1)
        y = (df['Personality'] == 'Introvert').astype(int)

        cat_cols = ['Stage_fear', 'Drained_after_socializing']
        label_encoders = {}
        for col in cat_cols:
            if col in X.columns:
                le = LabelEncoder()
                X[col] = le.fit_transform(X[col].astype(str))
                label_encoders[col] = le

        return X, y, label_encoders

    def _create_features(self, df):
        import pandas as pd
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

        num_cols = [c for c in ['Time_spent_Alone', 'Social_event_attendance',
                                 'Going_outside', 'Friends_circle_size', 'Post_frequency']
                    if c in df.columns]
        for i, c1 in enumerate(num_cols):
            for c2 in num_cols[i + 1:]:
                df[f'{c1}_{c2}_interaction'] = df[c1] * df[c2]

        for col in ['Social_event_attendance', 'Time_spent_Alone', 'Going_outside']:
            if col in df.columns:
                df[f'{col}_squared'] = df[col] ** 2
        return df

    def _default_catboost_params(self):
        return {
            'iterations': 2000, 'learning_rate': 0.05, 'depth': 8,
            'l2_leaf_reg': 3, 'random_strength': 1,
            'random_state': 42, 'verbose': False,
        }

    def _optimize_catboost(self, X_tr, y_tr, X_val, y_val, n_trials):
        import optuna
        from catboost import CatBoostClassifier
        from sklearn.metrics import accuracy_score

        def objective(trial):
            p = {
                'iterations':             trial.suggest_int('iterations', 500, 3000),
                'learning_rate':          trial.suggest_float('learning_rate', 0.005, 0.1, log=True),
                'depth':                  trial.suggest_int('depth', 4, 10),
                'l2_leaf_reg':            trial.suggest_float('l2_leaf_reg', 1e-3, 10, log=True),
                'random_strength':        trial.suggest_float('random_strength', 0.1, 10),
                'bagging_temperature':    trial.suggest_float('bagging_temperature', 0.0, 1.0),
                'random_state': 42, 'verbose': False,
            }
            m = CatBoostClassifier(**p)
            m.fit(X_tr, y_tr, eval_set=(X_val, y_val),
                  early_stopping_rounds=50, verbose=False)
            return accuracy_score(y_val, m.predict(X_val))

        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        params = study.best_params
        params.update({'random_state': 42, 'verbose': False})
        return params

    def _train_ensemble(self, X_tr, y_tr, X_val, y_val, cat_params):
        import lightgbm as lgb
        from catboost import CatBoostClassifier
        from sklearn.ensemble import RandomForestClassifier

        self.stdout.write('  CatBoost...')
        cat = CatBoostClassifier(**cat_params)
        cat.fit(X_tr, y_tr, eval_set=(X_val, y_val),
                early_stopping_rounds=100, verbose=False)

        self.stdout.write('  LightGBM...')
        lgbm = lgb.LGBMClassifier(n_estimators=1000, learning_rate=0.05,
                                   max_depth=7, random_state=42, n_jobs=-1)
        lgbm.fit(X_tr, y_tr, eval_set=[(X_val, y_val)])

        self.stdout.write('  Random Forest...')
        rf = RandomForestClassifier(n_estimators=500, max_depth=10,
                                    random_state=42, n_jobs=-1)
        rf.fit(X_tr, y_tr)

        return {'catboost': cat, 'lightgbm': lgbm, 'random_forest': rf}

    def _ensemble_accuracy(self, models, weights, X_val, y_val):
        import numpy as np
        from sklearn.metrics import accuracy_score

        proba = np.zeros(X_val.shape[0])
        total = sum(weights.values())
        for name, model in models.items():
            p = model.predict_proba(X_val)[:, 1]
            proba += weights.get(name, 0.3) * p
        pred = (proba / total > 0.5).astype(int)
        return accuracy_score(y_val, pred)


# ── Ensemble wrapper  (makes the saved object behave like a single sklearn model) ──

class _EnsembleWrapper:
    """
    Wraps the three-model ensemble so it exposes
    predict() and predict_proba() like any sklearn estimator.
    Saved as a single .pkl — the handler loads it with pickle normally.
    """
    def __init__(self, models: dict, weights: dict):
        self.models  = models
        self.weights = weights

    def predict(self, X):
        import numpy as np
        return (self.predict_proba(X)[:, 1] > 0.5).astype(int)

    def predict_proba(self, X):
        import numpy as np
        proba = np.zeros(X.shape[0])
        total = sum(self.weights.values())
        for name, model in self.models.items():
            proba += self.weights.get(name, 0.3) * model.predict_proba(X)[:, 1]
        proba /= total
        return np.column_stack([1 - proba, proba])
