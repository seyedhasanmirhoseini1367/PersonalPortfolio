import threading
import time

from django.test import SimpleTestCase, TestCase, override_settings

from . import signals
from .models import Document
from .services.document_processor import DocumentProcessor


def wait_until(check, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


@override_settings(RAG_SYNC_DELAY=0.05)
class DebounceTests(SimpleTestCase):
    """Many saves in a row lead to one rebuild, never two at the same time."""

    def test_burst_of_saves_runs_once(self):
        calls = []
        for _ in range(30):
            signals._schedule(('burst',), calls.append, 'x')
        self.assertTrue(wait_until(lambda: calls == ['x']))
        time.sleep(0.15)
        self.assertEqual(calls, ['x'])

    def test_save_during_a_run_queues_one_more_run(self):
        started, release = threading.Event(), threading.Event()
        calls, active, overlap = [], [0], []

        def slow(_):
            active[0] += 1
            overlap.append(active[0] > 1)
            calls.append(1)
            started.set()
            release.wait(2)
            active[0] -= 1

        signals._schedule(('slow',), slow, None)
        self.assertTrue(started.wait(2))
        for _ in range(5):
            signals._schedule(('slow',), slow, None)
        release.set()
        self.assertTrue(wait_until(lambda: len(calls) == 2))
        time.sleep(0.15)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(overlap))

    def test_state_only_saves_are_ignored(self):
        self.assertTrue(signals._state_only({'update_fields': {'status', 'error_message'}}, signals._STATE_FIELDS_FILE))
        self.assertFalse(signals._state_only({'update_fields': None}, signals._STATE_FIELDS_FILE))
        self.assertFalse(signals._state_only({'update_fields': {'status', 'file'}}, signals._STATE_FIELDS_FILE))


class IngestTextTests(TestCase):
    def test_replaces_document_and_chunks(self):
        proc = DocumentProcessor()
        proc.ingest_text('first version ' * 50, 'Resume', 'resume', 'db:resume')
        doc = proc.ingest_text('second version ' * 50, 'Resume', 'resume', 'db:resume')
        self.assertEqual(Document.objects.filter(source='db:resume').count(), 1)
        self.assertTrue(doc.chunks.exists())
        self.assertIn('second', doc.chunks.first().content)
