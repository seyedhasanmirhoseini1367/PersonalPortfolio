"""
Management command: downloads the trained irrigation model from Azure ML
and wires it up to the project record automatically.

No manual file upload needed — this replaces the Admin upload step.

Usage:
    python manage.py download_irrigation_model
    python manage.py download_irrigation_model --model-version 2   # specific version
    python manage.py download_irrigation_model --force             # overwrite existing

Requirements (pip):
    azure-ai-ml  azure-identity
"""

import os
import pickle
import shutil
import tempfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

MODEL_NAME    = "irrigation-model"
MODEL_VERSION = "2"

SUBSCRIPTION_ID    = "55e3ff52-09b3-4231-985c-1362e939fc4b"
RESOURCE_GROUP     = "hasanai_group"
WORKSPACE_NAME     = "hasanai-ml"

# Artifacts the irrigation_predictor handler expects alongside model.pkl
ARTIFACT_SUFFIXES = [
    "_target_encoder",
    "_label_encoders",
    "_feature_names",
    "_categorical_features",
]

DEST_MODEL_NAME = "irrigationmodel"   # base filename stored in media


class Command(BaseCommand):
    help = "Download irrigation model from Azure ML and attach it to the project."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model-version",
            default=MODEL_VERSION,
            help=f"Azure ML model version to download (default: {MODEL_VERSION})",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing model files if present.",
        )

    def handle(self, *args, **options):
        version = options["model_version"]
        force   = options["force"]

        # ── 1. Find project record ────────────────────────────────────────────
        from projects.models import Projects
        project = Projects.objects.filter(title="Predicting Irrigation Need").first()
        if not project:
            raise CommandError(
                'Project "Predicting Irrigation Need" not found. '
                "Run first: python manage.py setup_irrigation_project"
            )

        dest_dir  = os.path.join(settings.MEDIA_ROOT, "projects", "models")
        dest_base = os.path.join(dest_dir, DEST_MODEL_NAME)
        dest_pkl  = f"{dest_base}.pkl"

        if os.path.exists(dest_pkl) and not force:
            self.stdout.write(self.style.WARNING(
                f"Model already exists at {dest_pkl}. Use --force to overwrite."
            ))
            # Still wire up the DB record if it's missing
            self._update_project(project, dest_pkl)
            return

        # ── 2. Connect to Azure ML ────────────────────────────────────────────
        self.stdout.write("Connecting to Azure ML...")
        try:
            from azure.ai.ml import MLClient
            from azure.identity import DefaultAzureCredential
        except ImportError:
            raise CommandError(
                "azure-ai-ml and azure-identity are required. "
                "Run: pip install azure-ai-ml azure-identity"
            )

        try:
            ml_client = MLClient(
                DefaultAzureCredential(),
                subscription_id=SUBSCRIPTION_ID,
                resource_group_name=RESOURCE_GROUP,
                workspace_name=WORKSPACE_NAME,
            )
        except Exception as e:
            raise CommandError(f"Failed to connect to Azure ML: {e}")

        # ── 3. Download model to a temp directory ─────────────────────────────
        self.stdout.write(f"Downloading {MODEL_NAME}:{version} from Azure ML...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                ml_client.models.download(
                    name=MODEL_NAME,
                    version=version,
                    download_path=tmp_dir,
                )
            except Exception as e:
                raise CommandError(f"Download failed: {e}")

            # Azure ML downloads to: tmp_dir/<model-name>/<artifact-folder>/
            dl_outputs = os.path.join(tmp_dir, MODEL_NAME, "outputs")
            if not os.path.isdir(dl_outputs):
                # Fallback: search for outputs folder
                for root, dirs, _ in os.walk(tmp_dir):
                    if "model.pkl" in os.listdir(root):
                        dl_outputs = root
                        break

            self.stdout.write(f"  Downloaded to: {dl_outputs}")
            downloaded = os.listdir(dl_outputs)
            self.stdout.write(f"  Files: {downloaded}")

            # ── 4. Prepare destination directory ──────────────────────────────
            os.makedirs(dest_dir, exist_ok=True)

            # ── 5. Copy model.pkl ─────────────────────────────────────────────
            src_model = os.path.join(dl_outputs, "model.pkl")
            if not os.path.exists(src_model):
                raise CommandError(f"model.pkl not found in {dl_outputs}")

            shutil.copy2(src_model, dest_pkl)
            self.stdout.write(self.style.SUCCESS(f"  Saved: {dest_pkl}"))

            # ── 6. Build and save companion artifacts ─────────────────────────
            with open(src_model, "rb") as f:
                model = pickle.load(f)

            with open(os.path.join(dl_outputs, "encoder.pkl"), "rb") as f:
                target_encoder = pickle.load(f)

            with open(os.path.join(dl_outputs, "categorical_features.pkl"), "rb") as f:
                categorical_features = pickle.load(f)

            feature_names  = list(model.feature_names_)
            label_encoders = {}   # CatBoost handles categoricals natively

            artifacts = {
                "_target_encoder":      target_encoder,
                "_label_encoders":      label_encoders,
                "_feature_names":       feature_names,
                "_categorical_features": categorical_features,
            }

            for suffix, obj in artifacts.items():
                path = f"{dest_base}{suffix}.pkl"
                with open(path, "wb") as f:
                    pickle.dump(obj, f)
                self.stdout.write(self.style.SUCCESS(
                    f"  Saved: {os.path.basename(path)}"
                ))

        # ── 7. Wire model file to the Django project record ───────────────────
        self._update_project(project, dest_pkl)

        self.stdout.write(self.style.SUCCESS(
            "\nDone! The irrigation model is ready. "
            "Test it at: /projects/<slug>/predict/"
        ))

    def _update_project(self, project, dest_pkl):
        """Save the model file reference to the project DB record."""
        from projects.models import Projects

        media_root    = str(settings.MEDIA_ROOT)
        relative_path = os.path.relpath(dest_pkl, media_root).replace("\\", "/")

        project.trained_model.name = relative_path
        project.prediction_endpoint    = True
        project.prediction_input_type  = "file"
        project.save(update_fields=["trained_model", "prediction_endpoint",
                                    "prediction_input_type"])

        self.stdout.write(self.style.SUCCESS(
            f"  Project updated — model path: {relative_path}"
        ))
