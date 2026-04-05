# projects/inference/registry.py
"""
Central registry that maps a project's inference_handler slug
(stored in file_input_config["handler"]) to a handler class.

Usage
-----
# In your handler file:
from projects.inference.registry import register
from projects.inference.base import InferenceHandler

@register("seizure_eeg")
class SeizureEEGHandler(InferenceHandler):
    ...

# In views.py:
from projects.inference import get_handler
handler = get_handler(project)
result  = handler.run(uploaded_file)
"""

_REGISTRY: dict = {}


def register(slug: str):
    """Decorator to register a handler class under a slug."""
    def decorator(cls):
        _REGISTRY[slug] = cls
        return cls
    return decorator


def get_handler(project):
    """
    Return an instantiated handler for this project.
    Raises ValueError with a clear message if the slug is missing or unknown.
    """
    cfg  = project.file_input_config or {}
    slug = cfg.get("handler", "").strip()

    if not slug:
        raise ValueError(
            f'Project "{project.title}" has no inference handler configured. '
            f'Set file_input_config["handler"] in Django admin. '
            f'Available handlers: {list(_REGISTRY.keys())}'
        )

    if slug not in _REGISTRY:
        raise ValueError(
            f'Unknown inference handler "{slug}" for project "{project.title}". '
            f'Available handlers: {list(_REGISTRY.keys())}. '
            f'Create a new handler in projects/inference/ and register it with @register("{slug}").'
        )

    return _REGISTRY[slug](project)
