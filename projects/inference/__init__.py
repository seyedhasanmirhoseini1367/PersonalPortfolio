# projects/inference/__init__.py
# Inference plugin registry.
# Each project registers an InferenceHandler subclass here.
from .registry import get_handler, register
from . import personality_predictor  # noqa: F401  # Add this line