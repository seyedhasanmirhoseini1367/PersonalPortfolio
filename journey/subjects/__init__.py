"""Registry of subjects. A space or group picks one when it is created; Finnish is the default."""
from .base import Subject
from .finnish import Finnish
from .general import General, Mathematics, Programming, Science

SUBJECTS = {s.key: s for s in (Finnish(), General(), Mathematics(), Programming(), Science())}
DEFAULT = Finnish.key


def get(key) -> Subject:
    return SUBJECTS.get(key) or SUBJECTS[DEFAULT]


def choices():
    return [(s.key, s.name) for s in SUBJECTS.values()]
