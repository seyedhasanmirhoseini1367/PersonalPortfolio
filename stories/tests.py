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
            self.assertEqual(collect(log=lambda m: None), {'papers': [], 'news': [], 'repos': [], 'hn': []})
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


from django.test import override_settings


@override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_CHANNEL_ID='AIFrontiers', SITE_URL='https://hasanai.net')
class TelegramTests(TestCase):
    """Digest announcements go to the channel only after the owner approves them."""

    def setUp(self):
        from unittest import mock
        self.calls = []

        def fake_api(method, **params):
            self.calls.append((method, params))
            if method == 'getMe':
                return {'username': 'hasanainews_bot'}
            return {'message_id': len(self.calls)}
        for target, kw in (('stories.telegram.api', {'side_effect': fake_api}),
                           ('stories.digest.translate_fa', {'return_value': 0})):
            patcher = mock.patch(target, **kw)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user('w4', 'w4@example.test', 'pw-writer-123!')
        self.story = Story.objects.create(
            author=self.user, title='AI & ML Digest — 22 Nov 2026', slug='ai-ml-digest-2026-11-22',
            status=Story.Status.PUBLISHED,
            content='<h2>Research papers</h2><h3><a href="https://arxiv.org/abs/1" target="_blank">Paper &amp; one</a></h3>'
                    '<p class="digest-meta"><a class="digest-topic" href="/stories/tag/llms/">LLMs</a></p><p>s</p>')

    def _sent(self, method):
        return [p for m, p in self.calls if m == method]

    def _link_admin(self, chat_id=42):
        from .models import TelegramConfig
        TelegramConfig.objects.update_or_create(pk=1, defaults={'admin_chat_id': chat_id})

    def test_channel_name_normalised(self):
        from . import telegram
        self.assertEqual(telegram.channel(), '@AIFrontiers')
        with override_settings(TELEGRAM_CHANNEL_ID='https://t.me/AIFrontiers'):
            self.assertEqual(telegram.channel(), '@AIFrontiers')
        with override_settings(TELEGRAM_CHANNEL_ID='-1001234'):
            self.assertEqual(telegram.channel(), '-1001234')

    def test_text_is_persian_with_a_source_per_item(self):
        from datetime import date
        from .models import DigestItem
        from .telegram import build_text
        text = build_text(self.story)   # no Persian yet: English title, still with its source
        self.assertIn('🔹 <b>Paper &amp; one</b>\n🔗 منبع: <a href="https://arxiv.org/abs/1">منبع</a>', text)
        DigestItem.objects.create(url='https://arxiv.org/abs/1', title='Paper & one', source='arXiv (via Hugging Face Daily Papers)',
                                  digest_date=date(2026, 11, 22), summary='s', fa_title='مقاله یک',
                                  fa_summary='این مقاله روشی تازه معرفی می‌کند.')
        text = build_text(self.story)
        self.assertIn('خلاصهٔ خبرهای هوش مصنوعی', text)
        self.assertIn('🔹 <b>مقاله یک</b>\nاین مقاله روشی تازه معرفی می‌کند.\n'
                      '🔗 منبع: <a href="https://arxiv.org/abs/1">arXiv</a>', text)
        self.assertIn('https://hasanai.net/stories/story/ai-ml-digest-2026-11-22/', text)
        self.assertIn('#LLMs', text)

    def test_queue_sends_draft_to_owner_not_channel(self):
        from .telegram import queue_post
        self._link_admin()
        post = queue_post(self.story)
        self.assertEqual(post.status, 'pending')
        sends = self._sent('sendMessage')
        self.assertEqual([s['chat_id'] for s in sends], [42])   # only the owner's chat
        self.assertEqual(sends[0]['reply_markup']['inline_keyboard'][0][0]['callback_data'], f'tg:pub:{post.pk}')
        self.assertIsNone(queue_post(self.story).channel_message_id)   # re-queue does not publish

    def test_owner_approves_in_telegram(self):
        from .telegram import handle_update, queue_post
        self._link_admin()
        post = queue_post(self.story)
        cb = {'id': 'c1', 'from': {'id': 99}, 'data': f'tg:pub:{post.pk}',
              'message': {'message_id': 7, 'chat': {'id': 99}}}
        handle_update({'callback_query': cb})   # a stranger: refused
        post.refresh_from_db()
        self.assertEqual(post.status, 'pending')
        handle_update({'callback_query': {**cb, 'from': {'id': 42}, 'message': {'message_id': 7, 'chat': {'id': 42}}}})
        post.refresh_from_db()
        self.assertEqual(post.status, 'sent')
        self.assertEqual(self._sent('sendMessage')[-1]['chat_id'], '@AIFrontiers')
        handle_update({'callback_query': {**cb, 'from': {'id': 42}}})   # second press: no second post
        self.assertEqual(sum(1 for s in self._sent('sendMessage') if s['chat_id'] == '@AIFrontiers'), 1)

    def test_link_owner_with_one_time_code(self):
        from .models import TelegramConfig
        from .telegram import handle_update, new_link_code
        code = new_link_code()
        handle_update({'message': {'text': '/start wrong', 'chat': {'id': 5, 'type': 'private'}}})
        self.assertIsNone(TelegramConfig.get().admin_chat_id)
        handle_update({'message': {'text': f'/start {code}', 'chat': {'id': 5, 'type': 'private', 'username': 'me'}}})
        cfg = TelegramConfig.get()
        self.assertEqual((cfg.admin_chat_id, cfg.admin_name, cfg.link_code), (5, 'me', ''))

    def test_webhook_needs_secret(self):
        import json
        from .telegram import webhook_secret
        body = json.dumps({'message': {'text': '/start', 'chat': {'id': 1, 'type': 'private'}}})
        self.assertEqual(self.client.post('/stories/telegram/webhook/', body, content_type='application/json').status_code, 403)
        r = self.client.post('/stories/telegram/webhook/', body, content_type='application/json',
                             HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=webhook_secret())
        self.assertEqual(r.status_code, 200)

    def test_review_page_staff_only_and_publish(self):
        from .models import TelegramPost
        post = TelegramPost.objects.create(story=self.story, text='<b>hi</b>')
        self.assertEqual(self.client.get('/stories/telegram/').status_code, 302)   # anonymous -> login
        staff = get_user_model().objects.create_user('st', 'st@example.test', 'pw-staff-123!', is_staff=True)
        self.client.force_login(staff)
        r = self.client.get('/stories/telegram/')
        self.assertContains(r, '@AIFrontiers')
        self.assertContains(r, 'Publish to channel')
        self.client.post('/stories/telegram/', {'action': 'publish', 'post': post.pk, 'text': '<b>edited</b>'})
        post.refresh_from_db()
        self.assertEqual((post.status, post.text), ('sent', '<b>edited</b>'))
        self.client.post('/stories/telegram/', {'action': 'link'})
        self.assertContains(self.client.get('/stories/telegram/'), 'https://t.me/hasanainews_bot?start=')

    def test_digest_run_drafts_a_post(self):
        from unittest import mock
        from .digest import run_today
        from .models import TelegramPost
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')
        items = [{'section': 'news', 'title': 'Lab ships model', 'url': 'https://lab.example/y', 'source': 'Lab',
                  'text': 't', 'date': None, 'summary': 'A lab shipped a model for papers.', 'why': 'Useful.'}]
        with mock.patch('stories.digest.collect', return_value={'papers': [], 'news': items, 'hn': []}), \
             mock.patch('stories.digest.summarize', return_value=items):
            rec = run_today()
        self.assertEqual(TelegramPost.objects.get(story=rec.story).status, 'pending')
        self.assertFalse([s for s in self._sent('sendMessage') if s['chat_id'] == '@AIFrontiers'])


class NewsDeskTests(TestCase):
    """Editor's links, website sources, varied style labels, Persian translation."""

    def setUp(self):
        get_user_model().objects.create_superuser('seyed', 'a@example.test', 'pw-admin-123!')

    def test_feed_found_from_a_website(self):
        from unittest import mock
        from .digest import discover_feed, feed_items
        from .models import NewsSource
        page = b'<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>x</body></html>'
        self.assertEqual(discover_feed('https://site.example/blog/', page), 'https://site.example/feed.xml')
        src = NewsSource.objects.create(name='Site', url='https://site.example/blog/')
        with mock.patch('stories.digest._get', side_effect=[page, RSS]):
            items = feed_items(src)
        self.assertEqual(items[0]['url'], 'https://example.com/a')
        src.refresh_from_db()
        self.assertEqual(src.url, 'https://site.example/feed.xml')   # remembered

    def test_github_link_is_read_via_api(self):
        from unittest import mock
        from .digest import link_info
        with mock.patch('stories.digest._github_api', return_value={'full_name': 'VectifyAI/PageIndex',
                                                                     'description': 'Reasoning-based RAG without vectors'}), \
             mock.patch('stories.digest._get', return_value=b'# PageIndex\nA document index for reasoning-based retrieval.'):
            info = link_info('https://github.com/VectifyAI/PageIndex')
        self.assertEqual(info['title'], 'VectifyAI/PageIndex: Reasoning-based RAG without vectors')
        self.assertEqual(info['source'], 'GitHub')
        self.assertIn('document index', info['text'])

    def _fake_summarize(self, items, log=print):
        return [{**i, 'summary': f'About {i["title"]}.', 'why': 'Try it out today.', 'angle': 'Try it', 'topic': 'LLMs'}
                for i in items]

    def test_editor_links_lead_the_digest(self):
        from unittest import mock
        from .digest import run_today
        from .models import SuggestedLink
        link = SuggestedLink.objects.create(url='https://github.com/VectifyAI/PageIndex', note='Vectorless RAG.')
        news = [{'section': 'news', 'title': 'Lab ships model', 'url': 'https://lab.example/z', 'source': 'Lab',
                 'text': 't', 'date': None}]
        info = {'title': 'VectifyAI/PageIndex: Reasoning-based RAG', 'text': 'A tree index of long documents for retrieval.', 'source': 'GitHub'}
        with mock.patch('stories.digest.collect', return_value={'papers': [], 'news': news, 'repos': [], 'hn': []}), \
             mock.patch('stories.digest.link_info', return_value=info), \
             mock.patch('stories.digest.summarize', side_effect=self._fake_summarize):
            rec = run_today()
        content = rec.story.content
        self.assertLess(content.index("Editor&#x27;s picks"), content.index('From the labs'))
        self.assertIn('<strong>Try it:</strong>', content)   # the label varies per item
        link.refresh_from_db()
        self.assertEqual(link.status, 'used')
        self.assertEqual(rec.story.digest_overview['sections'][0], '1 pick')

    def test_add_picks_now_to_todays_digest(self):
        from unittest import mock
        from .digest import add_picks_now, publish
        from .models import SuggestedLink
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        today = timezone.now().astimezone(ZoneInfo('Europe/Helsinki')).date()
        publish([{'section': 'news', 'title': 'Old item', 'url': 'https://lab.example/old', 'source': 'Lab',
                  'text': 't', 'date': None, 'summary': 'An earlier item of the day.', 'why': ''}], today)
        SuggestedLink.objects.create(url='https://blog.example/post')
        info = {'title': 'A good post', 'text': 'A long enough description of the post for a summary.', 'source': 'blog.example'}
        with mock.patch('stories.digest.link_info', return_value=info), \
             mock.patch('stories.digest.summarize', side_effect=self._fake_summarize):
            story, n = add_picks_now()
        self.assertEqual(n, 1)
        self.assertLess(story.content.index('A good post'), story.content.index('Old item'))

    def test_unreadable_link_is_reported(self):
        from unittest import mock
        from .digest import editor_picks
        from .models import SuggestedLink
        link = SuggestedLink.objects.create(url='https://blog.example/empty')
        with mock.patch('stories.digest.link_info', return_value={'title': 'x', 'text': '', 'source': 'blog.example'}):
            self.assertEqual(editor_picks(log=lambda m: None), [])
        link.refresh_from_db()
        self.assertEqual(link.status, 'failed')
        self.assertIn('add a note', link.error)

    def test_persian_translation_is_grounded(self):
        import json
        from datetime import date
        from unittest import mock
        from .digest import translate_fa
        from .models import DigestItem
        r = DigestItem.objects.create(url='https://a.example', title='Model X', source='Lab', digest_date=date(2026, 11, 22),
                                      summary='Model X is 2 times faster.', why='Cheaper.')
        reply = json.dumps({'items': [{'n': 0, 'title': 'مدل X', 'summary': 'مدل X دو برابر سریع‌تر است. هزینه را ۵۰ درصد کم می‌کند.'}]})
        with mock.patch('content_generator.pipeline.agents.gemini_client.generate', return_value=reply):
            self.assertEqual(translate_fa([r]), 1)
        r.refresh_from_db()
        self.assertEqual(r.fa_title, 'مدل X')
        self.assertNotIn('۵۰', r.fa_summary)   # invented number dropped

    def test_news_desk_page(self):
        from unittest import mock
        from .models import NewsSource, SuggestedLink
        self.assertEqual(self.client.get('/stories/telegram/').status_code, 302)
        self.client.force_login(get_user_model().objects.get(username='seyed'))
        r = self.client.get('/stories/telegram/')
        self.assertContains(r, 'News desk')
        self.assertContains(r, 'GitHub trending AI repos')
        self.assertContains(self.client.get('/'), 'News Desk')   # in the profile menu for staff
        self.client.post('/stories/telegram/', {'action': 'add_link', 'url': 'https://github.com/VectifyAI/PageIndex'})
        self.client.post('/stories/telegram/', {'action': 'add_link', 'url': 'not a url'})
        self.assertEqual(list(SuggestedLink.objects.values_list('url', flat=True)), ['https://github.com/VectifyAI/PageIndex'])
        with mock.patch('stories.digest.feed_items', return_value=[{}]):
            self.client.post('/stories/telegram/', {'action': 'add_source', 'name': 'The Batch',
                                                    'url': 'https://www.deeplearning.ai/the-batch/', 'ai_filter': 'on'})
        src = NewsSource.objects.get(name='The Batch')
        self.assertTrue(src.ai_filter and src.active)
        self.client.post('/stories/telegram/', {'action': 'toggle_source', 'source': src.pk})
        src.refresh_from_db()
        self.assertFalse(src.active)


class GithubSpamTests(TestCase):
    def test_star_spam_filtered(self):
        from .digest import _looks_like_star_spam
        self.assertTrue(_looks_like_star_spam({'created_at': '2026-11-19T14:43:10Z', 'pushed_at': '2026-11-19T14:44:11Z',
                                               'stargazers_count': 2706, 'forks_count': 36}))
        self.assertFalse(_looks_like_star_spam({'created_at': '2026-11-09T00:50:28Z', 'pushed_at': '2026-11-22T05:21:25Z',
                                                'stargazers_count': 1917, 'forks_count': 368}))


TRENDING_HTML = '''<html><article class="Box-row"><h2 class="h3 lh-condensed">
<a data-x="1" href="/VectifyAI/PageIndex" class="Link"><span>VectifyAI /</span> PageIndex</a></h2>
<p class="col-9 color-fg-muted my-1">Document index for vectorless, reasoning-based RAG</p>
<a href="/VectifyAI/PageIndex/stargazers" class="Link"><svg></svg>
        40,712</a>
<span class="d-inline-block float-sm-right"><svg></svg> 2,345 stars this week</span></article>
<article class="Box-row"><h2><a href="/someone/web-ui-kit" class="Link">kit</a></h2>
<p class="col-9">A design system for web apps</p><span>99 stars this week</span></article></html>'''


@override_settings(TELEGRAM_BOT_TOKEN='123:test-token', TELEGRAM_CHANNEL_ID='AIFrontiers', SITE_URL='https://hasanai.net')
class RepoRadarTests(TestCase):
    """Weekly personal GitHub radar: collect, rank by weekly growth, summarise, deliver to the owner."""

    def setUp(self):
        from unittest import mock
        self.calls = []

        def fake_api(method, **params):
            self.calls.append((method, params))
            return {'message_id': len(self.calls)}
        p = mock.patch('stories.telegram.api', side_effect=fake_api)
        p.start()
        self.addCleanup(p.stop)

    def test_parse_trending(self):
        from .radar import parse_trending
        rows = parse_trending(TRENDING_HTML)
        self.assertEqual(rows[0], {'full_name': 'VectifyAI/PageIndex', 'stars': 40712, 'weekly_gain': 2345,
                                   'description': 'Document index for vectorless, reasoning-based RAG'})
        self.assertEqual(rows[1]['weekly_gain'], 99)

    def test_rank_keeps_relevant_growing_repos_and_snapshots(self):
        from datetime import timedelta
        from django.utils import timezone
        from .models import RadarConfig, RadarRepo
        from .radar import rank
        cfg = RadarConfig.get()
        found = {
            'VectifyAI/PageIndex': {'full_name': 'VectifyAI/PageIndex', 'description': 'vectorless RAG',
                                    'weekly_gain': 2345, 'stars': 40712, 'topics': []},
            'someone/web-ui-kit': {'full_name': 'someone/web-ui-kit', 'description': 'A design system',
                                   'weekly_gain': 99, 'stars': 500, 'topics': []},
            'org/mlops-kit': {'full_name': 'org/mlops-kit', 'description': 'Model serving and monitoring',
                              'weekly_gain': 0, 'stars': 1300, 'topics': ['mlops']},
        }
        RadarRepo.objects.create(full_name='org/mlops-kit', stars=1000, checked_at=timezone.now() - timedelta(days=7))
        out = rank(found, cfg, measure=0)
        self.assertEqual([c['full_name'] for c in out], ['VectifyAI/PageIndex', 'org/mlops-kit'])   # off-topic dropped
        self.assertEqual(out[1]['weekly_gain'], 300)   # from last week's snapshot
        self.assertEqual(RadarRepo.objects.get(full_name='org/mlops-kit').stars, 1300)

    def test_spread_takes_turns_across_topics(self):
        from .radar import spread
        cands = [{'full_name': f'a/{i}', 'matched': ['ai-agents']} for i in range(5)] + \
                [{'full_name': 'b/rag', 'matched': ['rag']}]
        self.assertEqual([c['full_name'] for c in spread(cands, ['rag', 'ai-agents'], 3)], ['b/rag', 'a/0', 'a/1'])

    def test_run_sends_to_owner_and_button_adds_to_digest(self):
        import json
        from unittest import mock
        from .models import RadarRepo, RadarRun, SuggestedLink, TelegramConfig
        from .radar import run
        from .telegram import handle_update
        TelegramConfig.objects.update_or_create(pk=1, defaults={'admin_chat_id': 42})
        found = {'VectifyAI/PageIndex': {'full_name': 'VectifyAI/PageIndex', 'description': 'vectorless RAG for long documents',
                                         'weekly_gain': 2345, 'stars': 40712, 'topics': []}}
        reply = json.dumps({'items': [{'n': 0, 'what': 'A tree index that lets an LLM reason its way to the right pages.',
                                       'for_you': 'Try it on long PDFs instead of a vector store.', 'relevant': True}]})
        with mock.patch('stories.radar.collect', return_value=found), \
             mock.patch('stories.digest.github_text', return_value='vectorless RAG for long documents'), \
             mock.patch('content_generator.pipeline.agents.gemini_client.generate', return_value=reply):
            rec = run()
        self.assertEqual(rec.status, 'done')
        repo = RadarRepo.objects.get(full_name='VectifyAI/PageIndex')
        self.assertEqual(rec.picked, [repo.pk])
        sent = [p for m, p in self.calls if m == 'sendMessage']
        self.assertEqual(sent[0]['chat_id'], 42)   # the owner's private chat, never the channel
        self.assertIn('VectifyAI/PageIndex', sent[0]['text'])
        self.assertIn('+2,345 this week', sent[0]['text'])
        self.assertEqual(sent[0]['reply_markup']['inline_keyboard'][0][0]['callback_data'], f'rr:add:{repo.pk}')
        handle_update({'callback_query': {'id': 'c', 'from': {'id': 7}, 'data': f'rr:add:{repo.pk}'}})   # stranger
        self.assertFalse(SuggestedLink.objects.exists())
        handle_update({'callback_query': {'id': 'c', 'from': {'id': 42}, 'data': f'rr:add:{repo.pk}'}})
        self.assertEqual(SuggestedLink.objects.get().url, 'https://github.com/VectifyAI/PageIndex')
        self.assertTrue(RadarRepo.objects.get(pk=repo.pk).added)
        self.assertEqual(RadarRun.objects.count(), 1)

    def test_due_on_monday_morning_once(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .models import RadarRun
        from .radar import is_due
        hel = ZoneInfo('Europe/Helsinki')
        self.assertFalse(is_due(datetime(2026, 11, 23, 8, 0, tzinfo=hel)))    # Monday, too early
        self.assertTrue(is_due(datetime(2026, 11, 23, 9, 30, tzinfo=hel)))
        self.assertFalse(is_due(datetime(2026, 11, 24, 9, 30, tzinfo=hel)))   # Tuesday
        RadarRun.objects.create()
        self.assertFalse(is_due(timezone_now_monday()))

    def test_news_desk_section(self):
        from unittest import mock
        from .models import RadarConfig
        staff = get_user_model().objects.create_user('st2', 'st2@example.test', 'pw-staff-123!', is_staff=True)
        self.client.force_login(staff)
        r = self.client.get('/stories/telegram/')
        self.assertContains(r, 'Repo Radar')
        self.client.post('/stories/telegram/', {'action': 'radar_save', 'topics': 'rag, mlops', 'profile': 'Me.'})
        cfg = RadarConfig.get()
        self.assertEqual((cfg.topics, cfg.profile, cfg.enabled), ('rag, mlops', 'Me.', False))
        with mock.patch('stories.radar.start_in_background', return_value=True) as start:
            self.client.post('/stories/telegram/', {'action': 'radar_run'})
        start.assert_called_once()


def timezone_now_monday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo('Europe/Helsinki'))
