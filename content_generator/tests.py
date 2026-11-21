from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import CompanyProfile, GenerationJob
from .views import DAILY_JOB_LIMIT

User = get_user_model()


@mock.patch('content_generator.views.threading.Thread')
class AccessTests(TestCase):
    """Every signed-in user can use the generator, within a daily budget."""

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
        self.assertEqual(thread.call_count, DAILY_JOB_LIMIT)
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(GenerationJob.objects.filter(owner=self.ana).count(), DAILY_JOB_LIMIT)

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
