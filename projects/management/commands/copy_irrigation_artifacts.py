"""
Management command: copies the artifact .pkl files produced by the training
script into the Django media directory, next to the uploaded model file.

Run AFTER:
  1. Training script has been run (artifacts exist on disk)
  2. Model .pkl has been uploaded via Admin (so Django knows the media path)

Usage:
    python manage.py copy_irrigation_artifacts --source "D:/datasets/playground-series-s6/playground-series-s6e4"
"""

import os
import shutil
from django.core.management.base import BaseCommand, CommandError
from projects.models import Projects


ARTIFACT_SUFFIXES = [
    "_target_encoder",
    "_label_encoders",
    "_feature_names",
    "_categorical_features",
    "_model_type",
]


class Command(BaseCommand):
    help = "Copy irrigation model artifacts to the Django media directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Directory where the training script saved the .pkl files.",
        )

    def handle(self, *args, **options):
        source_dir = options["source"].replace("\\", "/")

        # Find the project
        project = Projects.objects.filter(title="Predicting Irrigation Need").first()
        if not project:
            raise CommandError(
                'Project "Predicting Irrigation Need" not found. '
                "Run: python manage.py setup_irrigation_project"
            )

        if not project.trained_model:
            raise CommandError(
                "No model file uploaded yet. "
                "Upload the .pkl file via Admin first, then run this command."
            )

        # Destination = same directory as the uploaded model file
        model_path   = project.trained_model.path          # absolute path
        model_base   = os.path.splitext(model_path)[0]     # strip .pkl
        dest_dir     = os.path.dirname(model_path)

        # Find source artifacts — look for any best_model_*.pkl base name
        source_base = None
        for fname in os.listdir(source_dir):
            if fname.startswith("best_model_") and fname.endswith("_model_type.pkl"):
                source_base = os.path.join(
                    source_dir,
                    fname.replace("_model_type.pkl", "")
                )
                break

        if not source_base:
            raise CommandError(
                f"No artifact files found in {source_dir}. "
                "Run the training script first."
            )

        self.stdout.write(f"Source base : {source_base}")
        self.stdout.write(f"Destination : {model_base}")

        copied = 0
        for suffix in ARTIFACT_SUFFIXES:
            src = f"{source_base}{suffix}.pkl"
            dst = f"{model_base}{suffix}.pkl"

            if not os.path.exists(src):
                self.stdout.write(self.style.WARNING(f"  MISSING  {os.path.basename(src)}"))
                continue

            shutil.copy2(src, dst)
            self.stdout.write(self.style.SUCCESS(f"  COPIED   {os.path.basename(dst)}"))
            copied += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {copied}/{len(ARTIFACT_SUFFIXES)} artifacts copied."
        ))
        if copied == len(ARTIFACT_SUFFIXES):
            self.stdout.write(
                "\nSmoke test:\n"
                "  python manage.py shell -c \"\n"
                "  from projects.models import Projects\n"
                "  from projects.inference import get_handler\n"
                "  p = Projects.objects.get(title='Predicting Irrigation Need')\n"
                "  h = get_handler(p)\n"
                "  print(type(h).__name__, h.accepted_extensions)\n"
                "  \""
            )
