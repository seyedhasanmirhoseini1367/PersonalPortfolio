"""Registry of subjects. A space or group picks one when it is created; Finnish is the default.

An unknown key is an error, never a silent switch to Finnish: building a lesson for a space
whose subject is not registered fails with a clear message (see get), while pages that only
show the subject's name use display() so they still open.
"""
from .base import Subject
from .finnish import Finnish
from .general import General, Mathematics, Programming, Science

SUBJECTS = {s.key: s for s in (Finnish(), General(), Mathematics(), Programming(), Science())}
DEFAULT = Finnish.key


class UnknownSubject(ValueError):
    def __init__(self, key):
        super().__init__(f'The subject “{key}” is not supported. Supported: {", ".join(SUBJECTS)}.')
        self.key = key


class Unsupported(Subject):
    """Stands in for a key that is no longer registered, so its pages render; it never builds anything."""
    icon = 'fa-circle-question'

    def __init__(self, key):
        self.key, self.name = key, f'Unsupported subject ({key})'
        self.description = 'This subject is not available any more. Existing lessons can still be practised.'

    def build(self, source, lookup=None, note=lambda msg: None, context=None):
        raise UnknownSubject(self.key)


def get(key) -> Subject:
    """The registered subject for key; raises UnknownSubject otherwise."""
    if key in SUBJECTS:
        return SUBJECTS[key]
    raise UnknownSubject(key)


def display(key) -> Subject:
    """For showing a space: the subject, or a stand-in that says it is unsupported."""
    return SUBJECTS.get(key) or Unsupported(key)


def is_supported(key):
    return key in SUBJECTS


def choices():
    return [(s.key, s.name) for s in SUBJECTS.values()]
