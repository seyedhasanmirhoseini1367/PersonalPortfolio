"""
Management command: creates (or updates) the Irrigation Need Prediction project
record in the database, ready for the model file to be uploaded via Admin.

Usage:
    python manage.py setup_irrigation_project
    python manage.py setup_irrigation_project --update   # overwrite if exists
"""

import json
from django.core.management.base import BaseCommand
from projects.models import Projects


PROJECT_DATA = {
    "title": "Predicting Irrigation Need",
    "description": (
        "A multi-class classification system that predicts agricultural irrigation "
        "requirements based on field and weather measurements. "
        "Three gradient-boosting models (CatBoost, LightGBM, XGBoost) were trained "
        "and the best-performing one was selected automatically."
    ),
    "short_description": (
        "Predicts irrigation need (Low / Medium / High) from field and weather data "
        "using ensemble gradient-boosting models."
    ),
    "project_type": "KAGGLE_COMPETITION",
    "skills": "Python,LightGBM,CatBoost,XGBoost,scikit-learn,pandas,numpy",
    "is_public": True,
    "is_featured": True,
    "prediction_endpoint": True,
    "prediction_input_type": "file",
    "github_url": "",
    "kaggle_url": "https://www.kaggle.com/competitions/playground-series-s6e4",
    "file_input_config": json.dumps({
        "handler":          "irrigation_predictor",
        "accepted_formats": ["csv"],
        "description": (
            "Upload a CSV file with one or more rows of field/weather measurements. "
            "The model will predict the irrigation need for each row."
        ),
    }, indent=2),
}


class Command(BaseCommand):
    help = "Create or update the Irrigation Need Prediction project record."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update the project if it already exists.",
        )

    def handle(self, *args, **options):
        existing = Projects.objects.filter(title=PROJECT_DATA["title"]).first()

        if existing and not options["update"]:
            self.stdout.write(self.style.WARNING(
                f'Project "{PROJECT_DATA["title"]}" already exists (id={existing.pk}). '
                f"Use --update to overwrite."
            ))
            return

        if existing and options["update"]:
            for field, value in PROJECT_DATA.items():
                setattr(existing, field, value)
            existing.save()
            self.stdout.write(self.style.SUCCESS(
                f'Updated project "{existing.title}" (id={existing.pk})'
            ))
        else:
            project = Projects.objects.create(**PROJECT_DATA)
            self.stdout.write(self.style.SUCCESS(
                f'Created project "{project.title}" (id={project.pk})'
            ))
            self.stdout.write(
                "\nNext step: go to Admin → Projects → "
                f"'{PROJECT_DATA['title']}' → upload the trained model .pkl file."
            )
