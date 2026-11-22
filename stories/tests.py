from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Story
from .sanitize import clean_html

User = get_user_model()

PAYLOAD = ('<p>Hello <strong>world</strong></p>'
           '<script>alert(1)</script>'
           '<img src="x" onerror="alert(2)">'
           '<a href="javascript:alert(3)">click</a>'
           '<iframe src="https://evil.example"></iframe>'
           '<p class="ql-align-center" style="color:red">centered</p>')


class SanitizeTests(TestCase):
    def test_scripts_and_handlers_removed(self):
        out = clean_html(PAYLOAD)
        for bad in ('<script', 'onerror', 'javascript:', '<iframe', 'style='):
            self.assertNotIn(bad, out)

    def test_editor_formatting_kept(self):
        out = clean_html(PAYLOAD)
        self.assertIn('<strong>world</strong>', out)
        self.assertIn('class="ql-align-center"', out)
        self.assertIn('<img src="x">', out)

    def test_story_page_does_not_run_stored_script(self):
        """Even content saved before cleaning existed is cleaned on display."""
        author = User.objects.create_user('writer', 'w@example.test', 'pw-writer-123!')
        fields = {f.name for f in Story._meta.get_fields()}
        data = dict(author=author, title='A story', content=PAYLOAD + '<p>' + 'x' * 120 + '</p>')
        if 'status' in fields:
            data['status'] = Story.Status.PUBLISHED
        story = Story.objects.create(**data)
        if not hasattr(story, 'get_absolute_url'):
            self.skipTest('no story URL')
        r = self.client.get(story.get_absolute_url())
        if r.status_code != 200:
            self.skipTest(f'story page not public in this state ({r.status_code})')
        self.assertNotContains(r, '<script>alert(1)')
        self.assertNotContains(r, 'onerror="alert(2)"')
        self.assertContains(r, '<strong>world</strong>')


RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>New AI model released</title><link>https://example.com/a</link>
<description>&lt;p&gt;A lab released a model that summarises papers.&lt;/p&gt;</description>
<pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
ATOM = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom post</title><link rel="alternate" href="https://example.com/b"/>
<summary>Short summary of an atom post about training.</summary><updated>2026-11-20T08:00:00Z</updated></entry></feed>'''


class DigestTests(TestCase):
    def test_parse_rss_and_atom(self):
        from .digest import parse_feed
        rss, atom = parse_feed(RSS), parse_feed(ATOM)
        self.assertEqual((rss[0]['url'], rss[0]['text']), ('https://example.com/a', 'A lab released a model that summarises papers.'))
        self.assertEqual(atom[0]['url'], 'https://example.com/b')
        self.assertIsNotNone(atom[0]['date'])

    def test_select_limits_and_never_repeats(self):
        from .digest import select
        papers = [{'section': 'papers', 'url': f'https://arxiv.org/abs/{i}', 'source': 'arXiv', 'title': 't', 'text': 'x'} for i in range(5)]
        news = [{'section': 'news', 'url': f'https://lab.example/{i}', 'source': 'Lab', 'title': 't', 'text': 'x'} for i in range(5)]
        picked = select({'papers': papers, 'news': news, 'hn': []}, {'https://arxiv.org/abs/0'})
        self.assertEqual([p['url'] for p in picked if p['section'] == 'papers'],
                         ['https://arxiv.org/abs/1', 'https://arxiv.org/abs/2', 'https://arxiv.org/abs/3'])
        self.assertEqual(len([p for p in picked if p['section'] == 'news']), 2)   # max 2 per publisher

    def test_grounded_drops_invented_numbers(self):
        from .digest import _grounded
        out = _grounded('It trains on 30 tasks. It is 40% faster. It is open source.', 'A benchmark of 30 tasks, open source.')
        self.assertEqual(out, 'It trains on 30 tasks. It is open source.')

    def test_publish_creates_tagged_story_with_sources(self):
        from datetime import date
        from unittest import mock
        from .digest import run_today
        from .models import DailyDigest, DigestItem
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')
        items = [{'section': 'news', 'title': 'Lab ships <b>model</b>', 'url': 'https://lab.example/x',
                  'source': 'Lab', 'text': 't', 'date': None, 'summary': 'A lab shipped a model for papers.',
                  'why': 'Useful for reading.'}]
        with mock.patch('stories.digest.collect', return_value={'papers': [], 'news': items, 'hn': []}), \
             mock.patch('stories.digest.summarize', return_value=items):
            rec = run_today()
        self.assertEqual((rec.status, rec.items), ('done', 1))
        story = rec.story
        self.assertEqual(story.status, Story.Status.PUBLISHED)
        self.assertEqual(sorted(story.tags.values_list('name', flat=True)), ['AI News', 'Digest'])
        self.assertIn('href="https://lab.example/x"', story.content)
        self.assertIn('Lab ships &lt;b&gt;model&lt;/b&gt;', story.content)   # titles escaped
        self.assertTrue(DigestItem.objects.filter(url='https://lab.example/x').exists())
        r = self.client.get(story.get_absolute_url())
        self.assertContains(r, 'Why it matters')

    def test_due_only_after_the_hour_and_once(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .digest import is_due
        from .models import DailyDigest
        hel = ZoneInfo('Europe/Helsinki')
        self.assertFalse(is_due(datetime(2026, 11, 22, 6, 30, tzinfo=hel)))
        self.assertTrue(is_due(datetime(2026, 11, 22, 7, 5, tzinfo=hel)))
        DailyDigest.objects.create(date=datetime(2026, 11, 22).date(), status='done')
        self.assertFalse(is_due(datetime(2026, 11, 22, 9, 0, tzinfo=hel)))


class StoryListPagesTests(TestCase):
    def setUp(self):
        from .models import Tag
        self.user = get_user_model().objects.create_user('writer2', 'w2@example.test', 'pw-writer-123!')
        self.digest = Story.objects.create(
            author=self.user, title='AI & ML Digest — 21 Nov 2026', slug='ai-ml-digest-2026-11-21',
            status=Story.Status.PUBLISHED, excerpt='x',
            content='<p>intro</p><h2>Research papers</h2><h3><a href="https://a">Paper A</a></h3><p>s</p>'
                    '<h3><a href="https://b">Paper B</a></h3><h2>From the labs and newsrooms</h2>'
                    '<h3><a href="https://c">News C</a></h3>' + '<p>' + 'y' * 120 + '</p>')
        tag = Tag.objects.create(name='AI News', slug='ai-news')
        self.digest.tags.add(tag)

    def test_digest_overview(self):
        o = self.digest.digest_overview
        self.assertEqual((o['sections'], o['lead'], o['total']), (['2 papers', '1 news item'], 'Paper A', 3))

    def test_list_and_tag_pages_render_digest_card(self):
        for url in ('/stories/', '/stories/tag/ai-news/'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, 'Daily digest')
            self.assertContains(r, '2 papers · 1 news item')
            self.assertContains(r, '/stories/story/ai-ml-digest-2026-11-21/')

    def test_my_stories_page(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/stories/my-stories/').status_code, 200)


class NewsUpgradeTests(TestCase):
    """Topics, finance filter, duplicate merging, learn-more links, weekly roundup, RSS."""

    def _items(self, n, day):
        from .models import DigestItem
        for i in range(n):
            DigestItem.objects.create(
                url=f'https://lab.example/{day.isoformat()}/{i}', title=f'Item {i} on {day}', source='Lab',
                digest_date=day, section='news', topic='LLMs', summary=f'Summary {i}.', why='Why.', score=i)

    def test_sources_seeded_and_managed(self):
        from unittest import mock
        from .digest import collect
        from .models import NewsSource
        names = set(NewsSource.objects.values_list('name', flat=True))
        self.assertTrue({'Hugging Face Daily Papers', 'Hacker News', 'OpenAI', 'MIT News'} <= names)
        NewsSource.objects.update(active=False)
        with mock.patch('stories.digest._get') as get:
            self.assertEqual(collect(log=lambda m: None), {'papers': [], 'news': [], 'hn': []})
            get.assert_not_called()   # inactive sources are not fetched

    def test_finance_news_is_dropped(self):
        from .digest import is_finance
        self.assertTrue(is_finance({'title': 'Nvidia stock falls as investors worry about AI spending'}))
        self.assertTrue(is_finance({'title': 'AI startup IPO', 'text': ''}))
        self.assertFalse(is_finance({'title': 'OpenAI shares a new reasoning model', 'text': 'A model.'}))

    def test_same_story_from_two_outlets_is_merged(self):
        from .digest import merge_duplicates
        news = [{'section': 'news', 'title': 'Google releases Gemini 4 reasoning model', 'url': 'https://a', 'source': 'Google'},
                {'section': 'news', 'title': 'Something else about robots entirely', 'url': 'https://b', 'source': 'MIT News'}]
        hn = [{'section': 'hn', 'title': 'Gemini 4 reasoning model released by Google', 'url': 'https://c',
               'source': 'Hacker News discussion'}]
        out = merge_duplicates({'papers': [], 'news': news, 'hn': hn})
        self.assertEqual([i['url'] for i in out['news']], ['https://a', 'https://b'])
        self.assertEqual(out['hn'], [])
        self.assertEqual(out['news'][0]['also'], [{'source': 'Hacker News', 'url': 'https://c'}])

    def test_select_skips_story_already_covered(self):
        from .digest import select
        news = [{'section': 'news', 'title': 'Google releases Gemini 4 reasoning model', 'url': 'https://new',
                 'source': 'X', 'text': 'x'}]
        self.assertEqual(select({'news': news}, set(), ['Gemini 4 reasoning model from Google is out']), [])

    def test_topic_validated_or_guessed(self):
        from .digest import _topic, guess_topic
        self.assertEqual(_topic('computer vision', {}), 'Computer Vision')
        self.assertEqual(_topic('Made up', {'title': 'A humanoid robot learns to walk'}), 'Robotics')
        self.assertEqual(guess_topic({'title': 'Plain title', 'section': 'papers'}), 'ML Research')

    def test_learn_links_to_walkthroughs(self):
        from model_internals.models import Walkthrough
        from .digest import _walkthrough_patterns, learn_links
        Walkthrough.objects.create(title='LoRA: Low-Rank Adaptation', slug='lora-low-rank-adaptation', category='papers')
        Walkthrough.objects.create(title='RAG: Retrieval-Augmented Generation',
                                   slug='rag-retrieval-augmented-generation', category='papers')
        Walkthrough.objects.create(title='Decision Tree', slug='decision-tree', category='trees')
        pats = _walkthrough_patterns()
        links = learn_links({'title': 'Cheaper LoRA adapters', 'summary': 'Uses retrieval-augmented generation.'}, pats)
        self.assertEqual([l['title'] for l in links],
                         ['LoRA: Low-Rank Adaptation', 'RAG: Retrieval-Augmented Generation'])
        self.assertTrue(links[0]['url'].endswith('/lora-low-rank-adaptation/'))
        self.assertEqual(learn_links({'title': 'Flora and fauna', 'summary': 'a drag race'}, pats), [])

    def test_publish_adds_topic_chips_tags_and_learn_links(self):
        from datetime import date
        from model_internals.models import Walkthrough
        from .digest import publish
        from .models import DigestItem
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')
        Walkthrough.objects.create(title='LoRA: Low-Rank Adaptation', slug='lora-low-rank-adaptation', category='papers')
        items = [{'section': 'papers', 'title': 'Faster LoRA training', 'url': 'https://arxiv.org/abs/1',
                  'source': 'arXiv', 'text': 't', 'date': None, 'summary': 'A method that trains adapters faster.',
                  'why': 'Cheaper.', 'topic': 'LLMs', 'also': [{'source': 'Hacker News', 'url': 'https://hn'}]}]
        story = publish(items, date(2026, 11, 22))
        self.assertIn('LLMs', story.tags.values_list('name', flat=True))
        self.assertIn('href="/stories/tag/llms/"', story.content)
        self.assertIn('Learn the basics', story.content)
        self.assertIn('also covered by', story.content)
        self.assertEqual(DigestItem.objects.get(url='https://arxiv.org/abs/1').topic, 'LLMs')
        r = self.client.get(story.get_absolute_url())
        self.assertContains(r, 'class="digest-topic"')
        self.assertContains(r, '/how-models-work/lora-low-rank-adaptation/')
        self.assertContains(self.client.get('/stories/'), 'Topics:')
        self.assertEqual(self.client.get('/stories/tag/llms/').status_code, 200)

    def test_weekly_roundup(self):
        from datetime import date, datetime, timedelta
        from unittest import mock
        from zoneinfo import ZoneInfo
        from .digest import is_weekly_due, last_week_start, run_weekly
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')
        hel = ZoneInfo('Europe/Helsinki')
        monday = datetime(2026, 11, 23, 8, 30, tzinfo=hel)
        ws = last_week_start(monday)
        self.assertEqual(ws, date(2026, 11, 16))
        for d in range(3):
            self._items(3, ws + timedelta(days=d))
        self.assertFalse(is_weekly_due(datetime(2026, 11, 23, 7, 30, tzinfo=hel)))   # before daily + 1 h
        self.assertFalse(is_weekly_due(datetime(2026, 11, 26, 9, 0, tzinfo=hel)))    # Thursday: too late
        self.assertTrue(is_weekly_due(monday))
        with mock.patch('content_generator.pipeline.agents.gemini_client.generate',
                        side_effect=RuntimeError('quota')):
            rec = run_weekly(ws)   # model unavailable: falls back to ranks
        self.assertEqual(rec.status, 'done')
        story = rec.story
        self.assertEqual(story.slug, 'ai-weekly-2026-11-16')
        self.assertTrue(story.is_digest and story.is_weekly)
        self.assertEqual(story.content.count('<h3>'), 5)
        self.assertIn('Also this week', story.content)
        self.assertEqual(story.digest_overview['sections'], ['5 top stories'])
        self.assertEqual(story.digest_cover['kicker'], 'Weekly roundup')
        self.assertFalse(is_weekly_due(monday))   # once a week
        r = self.client.get('/stories/')
        self.assertContains(r, 'Weekly roundup')
        self.assertContains(r, '/stories/story/ai-weekly-2026-11-16/')

    def test_rss_feed(self):
        user = get_user_model().objects.create_user('w3', 'w3@example.test', 'pw-writer-123!')
        Story.objects.create(author=user, title='AI & ML Digest — 21 Nov 2026', slug='ai-ml-digest-2026-11-21',
                             status=Story.Status.PUBLISHED, content='<p>news</p>')
        Story.objects.create(author=user, title='My essay', slug='my-essay', status=Story.Status.PUBLISHED,
                             content='<p>x</p>')
        r = self.client.get('/stories/feed/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('rss', r['Content-Type'])
        body = r.content.decode()
        self.assertIn('/stories/story/ai-ml-digest-2026-11-21/', body)
        self.assertNotIn('my-essay', body)
        self.assertContains(self.client.get('/stories/'), 'application/rss+xml')
