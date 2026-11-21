from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CompanyProfile, GenerationJob
DAILY_JOB_LIMIT = 10

User = get_user_model()


@override_settings(CONTENT_GENERATOR_DAILY_LIMIT=DAILY_JOB_LIMIT)
@mock.patch('content_generator.views.threading.Thread')
class AccessTests(TestCase):
    """Every signed-in user can use the generator, within an optional daily budget."""

    def setUp(self):
        self.ana = User.objects.create_user('ana', 'ana@example.test', 'pw-ana-123!')
        self.ben = User.objects.create_user('ben', 'ben@example.test', 'pw-ben-123!')

    def submit(self, **extra):
        data = {'content_formats': ['blog_post'], 'goal': 'Test', 'ab_variants': '1', **extra}
        return self.client.post(reverse('content_generator:submit'), data)

    def test_anonymous_is_sent_to_login(self, _thread):
        r = self.client.get(reverse('content_generator:form'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_any_user_sees_form_and_nav_link(self, _thread):
        self.client.force_login(self.ana)
        r = self.client.get(reverse('content_generator:form'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f'href="{reverse("content_generator:form")}"')
        self.assertContains(r, f'{DAILY_JOB_LIMIT} more generations today')

    def test_daily_limit(self, thread):
        self.client.force_login(self.ana)
        for _ in range(DAILY_JOB_LIMIT):
            self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(GenerationJob.objects.filter(status=GenerationJob.STATUS_PENDING).count(), DAILY_JOB_LIMIT)
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(GenerationJob.objects.filter(owner=self.ana).count(), DAILY_JOB_LIMIT)

    @override_settings(CONTENT_GENERATOR_DAILY_LIMIT=0)
    def test_no_limit_by_default(self, _thread):
        self.client.force_login(self.ana)
        self.assertNotContains(self.client.get(reverse('content_generator:form')), 'more generation')
        for _ in range(DAILY_JOB_LIMIT + 1):
            self.assertEqual(self.submit().status_code, 200)

    def test_staff_has_no_limit(self, _thread):
        self.ana.is_staff = True
        self.ana.save()
        self.client.force_login(self.ana)
        for _ in range(DAILY_JOB_LIMIT + 1):
            self.assertEqual(self.submit().status_code, 200)

    def test_unknown_formats_are_dropped(self, _thread):
        self.client.force_login(self.ana)
        self.submit(content_formats=['nope', 'blog_post', 'blog_post'])
        self.assertEqual(list(GenerationJob.objects.values_list('content_format', flat=True)), ['blog_post'])

    def test_cannot_use_someone_elses_profile(self, _thread):
        private = CompanyProfile.objects.create(owner=self.ben, name='Ben Co', about='secret about text')
        self.client.force_login(self.ana)
        self.submit(profile_id=str(private.pk))
        job = GenerationJob.objects.get(owner=self.ana)
        self.assertIsNone(job.company_profile)
        self.assertNotIn('secret', job.company_docs)


class KnowledgeSearchTests(TestCase):
    """Company knowledge is stored in the database and ranked with BM25."""

    def test_store_search_and_scopes(self):
        from .pipeline.agents.ingestion import ingest_scope_data, query_collection, ensure_company_indexed
        from .pipeline.agents.scope_detector import detect_scope
        ingest_scope_data('c1', 'about', 'Company About', 'We build a health app for patients in Finland.')
        ingest_scope_data('c1', 's1', 'Lab result explainer', 'Explains lab results and blood tests in plain words.')
        ingest_scope_data('c1', 's2', 'Medication reminders', 'Daily reminders and refill alerts.')
        self.assertIn('lab results', query_collection('c1', 'explain my blood test results', 1)[0])
        self.assertEqual(len(query_collection('c1', 'anything', 5, scope_ids=['s2'])), 1)
        self.assertEqual(detect_scope('Promote the lab result explainer', [('s1', 'Lab result explainer'), ('s2', 'Medication reminders')]), ['s1'])
        self.assertEqual(detect_scope('Post about the whole company', [('s1', 'Lab result explainer')]), [])
        ingest_scope_data('c1', 's1', 'Lab result explainer', 'Replaced text.')  # re-index replaces
        self.assertEqual(query_collection('c1', 'replaced', 5, scope_ids=['s1']), ['Replaced text.'])

        profile = CompanyProfile.objects.create(name='Acme', about='Acme makes rockets.')
        from .models import KnowledgeChunk
        KnowledgeChunk.objects.filter(client_id=f'company_{profile.pk}').delete()
        ensure_company_indexed(profile)
        self.assertEqual(query_collection(f'company_{profile.pk}', 'rockets', 1), ['Acme makes rockets.'])


class GroundingTests(TestCase):
    """Figures that are not in the source material are replaced with [ADD STAT]."""

    SOURCES = ('HealthCompass explains lab results in plain language. Used by 1,200 patients in '
               'Tampere since 2024. Rated 4.8/5.')

    def piece(self, **kw):
        from .pipeline.pydantic_models import ContentPiece
        return ContentPiece(title=kw.get('title', 'HealthCompass'), headline=kw.get('headline', ''),
                            sections=kw.get('sections', []), cta=kw.get('cta', ''))

    def test_invented_figures_removed_real_ones_kept(self):
        from .pipeline.agents.grounding import check_and_clean
        p = self.piece(
            headline='Reduces stress by 40% and helps 1,200 patients',
            sections=[{'heading': 'Why it works', 'body': 'Doctors save 3x time. Trusted by 500 clinics '
                       'for 10 years. Rated 4.8/5. Costs €29 a month. Since 2015.'}])
        clean, report = check_and_clean(p, self.SOURCES)
        text = clean.headline + ' ' + clean.sections[0]['body']
        for fake in ('40%', '3x', '500 clinics', '10 years', '€29', 'Since 2015'):
            self.assertNotIn(fake, text, fake)
        for real in ('1,200 patients', '4.8/5'):
            self.assertIn(real, text, real)
        self.assertEqual(report['placeholders'], 6)
        self.assertEqual({r['claim'] for r in report['removed']},
                         {'40%', '3x', '500 clinics', '10 years', '€29', 'Since 2015'})
        self.assertEqual(p.headline, 'Reduces stress by 40% and helps 1,200 patients')  # input untouched

    def test_attributions_and_unknown_quotes_flagged(self):
        from .pipeline.agents.grounding import check_and_clean
        p = self.piece(sections=[{'heading': 'Proof', 'body': 'Studies show patients feel calmer. '
                                  '“HealthCompass changed how I talk to my doctor,” says Anna.'}])
        _, report = check_and_clean(p, self.SOURCES)
        self.assertEqual(sorted(f['type'] for f in report['flagged']), ['quote', 'source'])

    def test_geo_judge_does_not_reward_invention(self):
        from .pipeline.agents.evaluator import judge_geo
        honest = judge_geo('What is HealthCompass?\n\nHealthCompass is an app that helps patients read lab '
                           'results. It cut waiting by [ADD STAT].')
        invented = judge_geo('What is HealthCompass?\n\nHealthCompass is an app that helps patients read lab '
                             'results. Studies show it cut waiting by 40%.')
        self.assertGreater(honest['score'], invented['score'])
        self.assertNotIn('statistic', ' '.join(honest['missing']).lower())


class ShortFormatTests(TestCase):
    def test_error_reply_is_not_content(self):
        from .pipeline.agents.content_writer import _content_json
        self.assertIsNone(_content_json('{"errors": ["Conflicting instructions"]}'))
        self.assertIsNone(_content_json('not json'))
        self.assertEqual(_content_json('[{"headline": "Clear lab results", "sections": []}]')['title'],
                         'Clear lab results')
        self.assertEqual(_content_json('{"content": {"title": "Tagline", "headline": "Know your results"}}')['headline'],
                         'Know your results')

    def test_geo_checks_follow_the_format(self):
        from .pipeline.agents.evaluator import judge_geo
        tagline = judge_geo('Tagline\n\nYour lab results, finally clear', 'motto')
        self.assertEqual((tagline['score'], [i['label'] for i in tagline['items']]), (100, ['No unsourced claims']))
        self.assertEqual(len(judge_geo('Some text.', 'blog_post')['items']), 5)


class JobQueueTests(TestCase):
    """Jobs wait in the database and the worker runs them in order."""

    def setUp(self):
        self.user = User.objects.create_user('queue_user', 'q@example.test', 'pw-queue-123!')

    def make_job(self, **kw):
        return GenerationJob.objects.create(owner=self.user, company_name='Acme', goal='g',
                                            content_format='motto', **kw)

    def test_submit_queues_instead_of_starting_a_thread(self):
        self.client.force_login(self.user)
        with mock.patch('content_generator.worker.wake') as wake:
            r = self.client.post(reverse('content_generator:submit'),
                                 {'content_formats': ['motto', 'social_post'], 'goal': 'g', 'ab_variants': '1',
                                  'word_count_min': '100'})
        self.assertEqual(r.status_code, 200)
        jobs = GenerationJob.objects.filter(owner=self.user)
        self.assertEqual(sorted(jobs.values_list('status', flat=True)), ['pending', 'pending'])
        self.assertEqual(jobs.first().seo_params['word_count_min'], 100)
        self.assertEqual(wake.call_count, 2)

    def test_worker_runs_oldest_first_and_reports_progress(self):
        from . import worker
        first, second = self.make_job(), self.make_job()
        seen = []

        def fake_run(job_id, seo_params, progress=None):
            progress(3, 'Writing')
            seen.append((job_id, GenerationJob.objects.get(pk=job_id).progress_label))
            GenerationJob.objects.filter(pk=job_id).update(status=GenerationJob.STATUS_DONE)

        with mock.patch('content_generator.views._run_pipeline_now', side_effect=fake_run):
            self.assertEqual(worker.run_pending(), 2)
        self.assertEqual(seen, [(str(first.pk), 'Writing'), (str(second.pk), 'Writing')])
        first.refresh_from_db()
        self.assertEqual((first.status, first.attempts, first.progress_step), ('done', 1, 3))
        self.assertIsNotNone(first.heartbeat_at)

    def test_interrupted_jobs_are_requeued_once_then_failed(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import worker
        old = timezone.now() - timedelta(minutes=30)
        retry = self.make_job(status='running', attempts=1, heartbeat_at=old)
        give_up = self.make_job(status='running', attempts=2, heartbeat_at=old)
        alive = self.make_job(status='running', attempts=1, heartbeat_at=timezone.now())
        self.assertEqual(worker.recover_stale(), 2)
        for job in (retry, give_up, alive):
            job.refresh_from_db()
        self.assertEqual((retry.status, give_up.status, alive.status), ('pending', 'failed', 'running'))
        self.assertIn('interrupted', give_up.error_message)

    def test_jobs_of_a_dead_process_are_requeued_sooner(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import worker
        five_min = timezone.now() - timedelta(minutes=5)
        orphan = self.make_job(status='running', attempts=1, heartbeat_at=five_min, claimed_by='old-host:1')
        mine = self.make_job(status='running', attempts=1, heartbeat_at=five_min, claimed_by=worker.WORKER_ID)
        worker.recover_stale()
        orphan.refresh_from_db(); mine.refresh_from_db()
        self.assertEqual((orphan.status, mine.status), ('pending', 'running'))

    def test_status_shows_queue_position_and_step(self):
        import uuid
        group = uuid.uuid4()
        from datetime import timedelta
        earlier = self.make_job(status='running', progress_step=4, progress_label='Checking facts')
        GenerationJob.objects.filter(pk=earlier.pk).update(created_at=earlier.created_at - timedelta(seconds=5))
        mine = self.make_job(job_group_id=group)
        self.client.force_login(self.user)
        data = self.client.get(reverse('content_generator:group_status', args=[group])).json()
        self.assertEqual(data['jobs'][0]['status'], 'pending')
        self.assertEqual(data['jobs'][0]['ahead'], 1)
        GenerationJob.objects.filter(pk=mine.pk).update(status='running', progress_step=3, progress_label='Writing')
        data = self.client.get(reverse('content_generator:group_status', args=[group])).json()
        self.assertEqual((data['jobs'][0]['step'], data['jobs'][0]['label']), (3, 'Writing'))
