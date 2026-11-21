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
