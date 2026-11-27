import io
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


class HomePageTests(TestCase):
    """The redesigned home page: hero, demos, numbers, news, ML Explained, Kaggle, contact band."""

    def test_sections_in_order(self):
        from datetime import date
        from django.contrib.auth import get_user_model
        from stories.digest import publish
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')
        publish([{'section': 'news', 'title': 'Lab ships a model', 'url': 'https://lab.example/h', 'source': 'Lab',
                  'text': 't', 'date': None, 'summary': 'A lab shipped a new open model.', 'why': '', 'topic': 'LLMs'}],
                date(2026, 11, 22))
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        order = ['hm-hero', 'AI demos you can use right now', 'ML models built', 'AI News</h2>', 'A lab shipped a new open model.',
                 'let’s work together']
        positions = [html.index(s) for s in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('<span>AI News</span>', html)   # nav renamed from Stories


class SiteSearchTests(TestCase):
    """Top-bar search across the site, and the live chip."""

    def test_search_groups_and_ranking(self):
        from django.utils import timezone
        from django.core.cache import cache
        from model_internals.models import Walkthrough
        from kaggle_archive.models import Competition
        cache.clear()
        Walkthrough.objects.create(title='Exploratory Data Analysis', slug='eda', category='foundations', summary='x')
        Walkthrough.objects.create(title='LoRA: Low-Rank Adaptation', slug='lora', category='papers', summary='y')
        today = timezone.localdate()
        Competition.objects.create(name='Predicting Credit Card Fraud', slug='playground-series-s6e11', series='playground',
                                   season=6, episode=11, start_date=today, end_date=today)
        data = self.client.get('/search/', {'q': 'lora'}).json()
        ml = next(g for g in data['groups'] if g['label'] == 'ML Explained')
        self.assertEqual(ml['items'][0]['title'], 'LoRA: Low-Rank Adaptation')   # title word match beats "exploratory"
        data = self.client.get('/search/', {'q': 'fraud'}).json()
        kg = next(g for g in data['groups'] if g['label'] == 'Kaggle')
        self.assertEqual(kg['items'][0]['sub'], f'Playground S6E11 · {today.year}')
        self.assertEqual(self.client.get('/search/', {'q': 'a'}).json()['groups'], [])
        r = self.client.get('/projects/')
        self.assertContains(r, 'Search or ask AI')
        self.assertContains(r, 'Kaggle S6E11 live')


class EnsureSuperuserTests(TestCase):
    """The admin must stay signed in across deploys: the command runs on every server start."""
    def test_password_is_written_only_when_it_changes(self):
        from unittest import mock
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        env = {'SUPERUSER_USERNAME': 'owner', 'SUPERUSER_PASSWORD': 'first-pass-123!'}
        with mock.patch.dict('os.environ', env):
            call_command('ensure_superuser', stdout=io.StringIO())
            user = get_user_model().objects.get(username='owner')
            first = user.password
            self.assertTrue(user.is_superuser and user.check_password('first-pass-123!'))
            call_command('ensure_superuser', stdout=io.StringIO())
            user.refresh_from_db()
            self.assertEqual(user.password, first, 'an unchanged password keeps its hash, so sessions stay valid')
        with mock.patch.dict('os.environ', dict(env, SUPERUSER_PASSWORD='second-pass-456!')):
            call_command('ensure_superuser', stdout=io.StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password('second-pass-456!'))

    def test_no_password_in_the_code(self):
        from unittest import mock
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        with mock.patch.dict('os.environ', {'SUPERUSER_USERNAME': 'fresh'}, clear=False):
            import os
            os.environ.pop('SUPERUSER_PASSWORD', None)
            call_command('ensure_superuser', stdout=io.StringIO())
        self.assertFalse(get_user_model().objects.get(username='fresh').has_usable_password())
