"""Registry of subjects. A group picks one when it is created; Finnish is the default."""
from .base import Subject
from .finnish import Finnish

SUBJECTS = {s.key: s for s in (Finnish(),)}
DEFAULT = Finnish.key


def get(key) -> Subject:
    return SUBJECTS.get(key) or SUBJECTS[DEFAULT]


def choices():
    return [(s.key, s.name) for s in SUBJECTS.values()]
