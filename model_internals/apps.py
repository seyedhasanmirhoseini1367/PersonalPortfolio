from django.apps import AppConfig


class ModelInternalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'model_internals'
    verbose_name = 'ML Explained'
