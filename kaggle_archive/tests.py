from django.test import TestCase


class LearningCardTests(TestCase):
    def test_bullets_with_unsupported_numbers_are_dropped(self):
        from .summarizer import _grounded, _numbers
        known = _numbers('We used 5-fold CV and lr 0.001 with EfficientNet-B5.')
        kept = _grounded(['5-fold group CV', 'lr 0.001', 'Gained 12% from TTA', 'EfficientNet-B5 backbone', 42], known)
        self.assertEqual(kept, ['5-fold group CV', 'lr 0.001', 'EfficientNet-B5 backbone'])

    def test_competition_page_shows_cards_and_hides_raw_writeups(self):
        from .models import Competition, Solution
        comp = Competition.objects.create(name='Demo Comp', slug='demo-comp',
                                          insights={'challenge': 'Noisy labels.', 'lessons': ['Trust CV.'],
                                                    'common': [], 'distinctive': [], 'based_on': 1})
        Solution.objects.create(competition=comp, rank=1, team_name='Team A', medal='gold',
                                writeup_content='<script>alert(1)</script> secret full text',
                                writeup_url='https://www.kaggle.com/x',
                                card={'headline': 'Strong CV.', 'validation': ['5-fold group CV'], 'models': ['GBDT']})
        r = self.client.get('/kaggle-winners-archive/demo-comp/')
        self.assertEqual(r.status_code, 200)
        for text in ('What the winners did', 'Trust CV.', 'Side by side', '5-fold group CV', 'Strong CV.'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'secret full text')
        self.assertNotContains(r, '<script>alert(1)')

    def test_markdown_filter_strips_scripts(self):
        from .templatetags.markdown_tags import render_markdown
        out = render_markdown('**bold** <img src=x onerror=alert(1)><script>x()</script>')
        self.assertIn('<strong>bold</strong>', out)
        self.assertNotIn('onerror', out)
        self.assertNotIn('<script', out)


class AutoSyncTests(TestCase):
    """Monthly archive update: which competitions get picked, and when."""

    def fake_api(self, comps):
        from types import SimpleNamespace
        listing = SimpleNamespace(competitions=[SimpleNamespace(**c) for c in comps])
        return SimpleNamespace(competitions_list=lambda **kw: listing)

    def test_candidates_window(self):
        from datetime import timedelta
        from django.utils import timezone
        from .auto import candidates
        now = timezone.now()
        api = self.fake_api([
            {'ref': 'https://www.kaggle.com/competitions/too-recent', 'title': 'A', 'deadline': now - timedelta(days=3), 'category': 'Featured'},
            {'ref': 'https://www.kaggle.com/competitions/good-one', 'title': 'B', 'deadline': now - timedelta(days=40), 'category': 'Featured'},
            {'ref': 'https://www.kaggle.com/competitions/too-old', 'title': 'C', 'deadline': now - timedelta(days=400), 'category': 'Research'},
            {'ref': 'https://www.kaggle.com/competitions/running', 'title': 'D', 'deadline': now + timedelta(days=30), 'category': 'Featured'},
        ])
        self.assertEqual([c['slug'] for c in candidates(api, now)], ['good-one'])

    def test_due_and_recheck_rules(self):
        from datetime import timedelta
        from django.utils import timezone
        from .auto import _needs_work, is_due
        from .models import KaggleSyncItem, KaggleSyncRun
        now = timezone.now()
        self.assertTrue(is_due(now))
        run = KaggleSyncRun.objects.create(status='done')
        self.assertFalse(is_due(now))
        KaggleSyncRun.objects.filter(pk=run.pk).update(started_at=now - timedelta(days=31))
        self.assertTrue(is_due(now))
        self.assertTrue(_needs_work(None, now))
        skipped = KaggleSyncItem(slug='s', status='skipped')
        few = KaggleSyncItem(slug='f', status='archived', writeups=1, last_checked=now - timedelta(days=40))
        fresh = KaggleSyncItem(slug='g', status='archived', writeups=1, last_checked=now - timedelta(days=5))
        plenty = KaggleSyncItem(slug='p', status='archived', writeups=5, last_checked=now - timedelta(days=90))
        self.assertEqual([_needs_work(i, now) for i in (skipped, few, fresh, plenty)], [False, True, False, False])

    def test_run_respects_limit_and_records_outcomes(self):
        from datetime import timedelta
        from unittest import mock
        from django.utils import timezone
        from .auto import run_sync
        from .models import Competition, KaggleSyncItem
        now = timezone.now()
        api = self.fake_api([
            {'ref': f'https://www.kaggle.com/competitions/c{i}', 'title': f'C{i}', 'deadline': now - timedelta(days=20 + i), 'category': 'Featured'}
            for i in range(4)])

        class FakeExtractor:
            def __init__(self, url, top_n, log_fn):
                self.url = url

            def run(self):
                if self.url == 'c1':
                    raise RuntimeError('Could not fetch leaderboard.')
                comp = Competition.objects.create(name=self.url, slug=self.url)
                return {'competition': comp, 'saved': 10}

        import kaggle
        with mock.patch.object(kaggle, 'api', api, create=True), \
             mock.patch.object(api, 'authenticate', lambda: None, create=True), \
             mock.patch('kaggle_archive.extractor.KaggleExtractor', FakeExtractor):
            run = run_sync('manual', limit=3)
        self.assertEqual((run.status, run.processed), ('done', 3))
        self.assertEqual(dict(KaggleSyncItem.objects.values_list('slug', 'status')),
                         {'c3': 'archived', 'c2': 'archived', 'c1': 'skipped'})


class TrendsTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from .models import Competition, Solution, Technique
        self.user = get_user_model().objects.create_user('learner', 'l@example.test', 'pw-learn-123!')
        self.comp = Competition.objects.create(
            name='Vision Comp', slug='vision-comp', competition_type='cv',
            insights={'lessons': ['Trust your CV.', 'Ensemble diverse backbones.'],
                      'common': [{'idea': 'Group k-fold', 'teams': ['A', 'B']}], 'distinctive': [], 'based_on': 2})
        tta = Technique.objects.create(name='TTA')
        for rank in (1, 2):
            s = Solution.objects.create(competition=self.comp, rank=rank, team_name=f'T{rank}')
            if rank == 1:
                s.techniques.add(tta)

    def test_trends_page_groups_by_type(self):
        r = self.client.get('/kaggle-winners-archive/trends/')
        self.assertEqual(r.status_code, 200)
        for text in ('Computer Vision', 'TTA', '50%', 'Group k-fold', 'Trust your CV.'):
            self.assertContains(r, text)

    def test_mark_lesson_learned(self):
        import json
        url = '/kaggle-winners-archive/vision-comp/learned/'
        body = json.dumps({'lesson': 'Trust your CV.'})
        self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, json.dumps({'lesson': 'made up'}), content_type='application/json').status_code, 400)
        self.assertTrue(self.client.post(url, body, content_type='application/json').json()['learned'])
        self.assertContains(self.client.get('/kaggle-winners-archive/trends/'), '<b>1</b> of 2 lessons learned', html=False)
        self.assertFalse(self.client.post(url, body, content_type='application/json').json()['learned'])
