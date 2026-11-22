import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from kaggle_archive.models import Competition
from stories.models import Story

from .management.commands.populate_content import FIXTURE
from .models import Projects


@override_settings(RAG_SYNC_DELAY=3600)  # no background re-indexing during the test
class PopulateContentTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser('seyed', 'admin@example.test', 'pw-admin-123!')

    def test_fixture_has_no_users_files_or_private_items(self):
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertFalse([o for o in data if o['model'].startswith('accounts.')])
        for o in data:
            for f in ('featured_image', 'trained_model', 'rag_document', 'author', 'owner'):
                self.assertIn(o['fields'].get(f, ''), ('', None))
            if o['model'] == 'projects.projects':
                self.assertTrue(o['fields']['is_public'])

    def test_loads_once_and_pages_work(self):
        call_command('populate_content', if_empty=True, verbosity=0)
        self.assertTrue(Projects.objects.exists())
        self.assertTrue(Competition.objects.exists())
        self.assertFalse(Story.objects.exists())   # sample stories are no longer seeded
        counts = (Projects.objects.count(), Competition.objects.count())

        Projects.objects.update(title='Edited in admin')
        call_command('populate_content', if_empty=True, verbosity=0)
        self.assertEqual((Projects.objects.count(), Competition.objects.count()), counts)
        self.assertFalse(Projects.objects.exclude(title='Edited in admin').exists())

        # Ids continue after the loaded rows.
        self.assertGreater(Projects.objects.create(title='New').pk, max(Projects.objects.values_list('pk', flat=True)[:counts[0]]))

        for url in ['/projects/', '/stories/', '/kaggle-winners-archive/']:
            self.assertEqual(self.client.get(url).status_code, 200, url)
