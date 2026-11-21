import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from .models import EventRSVP, PostSticker, SportPost
from . import views


def make_user(email, first_name=''):
    return get_user_model().objects.create_user(
        username=email, email=email, password='pw-for-tests-only', first_name=first_name)


class ApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user('alice@example.com', 'Alice')
        self.bob = make_user('bob@example.com', 'Bob')
        self.client = Client(enforce_csrf_checks=True)

    def login(self, user):
        self.client.force_login(user)
        self.client.get('/sports/')  # sets the CSRF cookie, like the real page

    def send(self, method, url, data=None, raw=None):
        token = self.client.cookies['csrftoken'].value
        body = raw if raw is not None else json.dumps(data or {})
        return getattr(self.client, method)(url, data=body, content_type='application/json',
                                            HTTP_X_CSRFTOKEN=token)

    def feed(self, query=''):
        return self.client.get('/sports/api/posts/' + query).json()


class PageAndAuthTests(ApiTestCase):
    def test_page_loads_and_sets_csrf_cookie(self):
        response = self.client.get('/sports/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sports Social App', response.content)
        self.assertIn('csrftoken', response.cookies)

    def test_me_when_logged_out_offers_login_back_to_sports(self):
        data = self.client.get('/sports/api/me/').json()
        self.assertFalse(data['authenticated'])
        self.assertTrue(data['login_url'].endswith('?next=/sports/'))

    def test_logged_out_user_cannot_post(self):
        self.client.get('/sports/')
        response = self.send('post', '/sports/api/posts/', {'sport': 'Football', 'text': 'hi'})
        self.assertEqual(response.status_code, 401)

    def test_post_requires_csrf_token(self):
        self.client.force_login(self.alice)
        response = self.client.post('/sports/api/posts/', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)


class PostTests(ApiTestCase):
    def test_create_post_and_see_it_in_feed(self):
        self.login(self.alice)
        response = self.send('post', '/sports/api/posts/', {'sport': 'Padel', 'text': 'Great match!'})
        self.assertEqual(response.status_code, 201)
        post = self.feed()['posts'][0]
        self.assertEqual((post['author']['name'], post['text'], post['can_delete']), ('Alice', 'Great match!', True))

    def test_feed_is_newest_first_even_with_comments(self):
        old = SportPost.objects.create(author=self.alice, sport='Padel', text='old')
        SportPost.objects.create(author=self.bob, sport='Padel', text='middle')
        SportPost.objects.create(author=self.alice, sport='Padel', text='new')
        old.comments.create(author=self.bob, text='c')
        self.assertEqual([p['text'] for p in self.feed()['posts']], ['new', 'middle', 'old'])

    def test_feed_pages_and_filters(self):
        for i in range(views.PAGE_SIZE + 3):
            SportPost.objects.create(author=self.alice, sport='Running' if i % 2 else 'Padel', text=f'p{i}')
        first = self.feed()
        self.assertEqual(len(first['posts']), views.PAGE_SIZE)
        second = self.feed(f"?before={first['next']}")
        self.assertEqual(len(second['posts']), 3)
        self.assertIsNone(second['next'])
        seen = [p['id'] for p in first['posts'] + second['posts']]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(all(p['sport'] == 'Running' for p in self.feed('?sport=Running')['posts']))
        self.assertEqual(self.feed(f'?author={self.bob.id}')['posts'], [])

    def test_rejects_bad_input_with_400_not_500(self):
        self.login(self.alice)
        url = '/sports/api/posts/'
        for body in ('[1,2]', '"str"', '{"sport":["Football"],"text":"x"}', '{"sport":"Padel","text":5}',
                     '{"sport":"Chess","text":"x"}', '{"sport":"Padel","text":"  "}', 'not json'):
            self.assertEqual(self.send('post', url, raw=body).status_code, 400, body)

    def test_missing_post_returns_json_404(self):
        self.login(self.alice)
        response = self.send('post', '/sports/api/posts/999/sticker/', {'sticker': 'fire'})
        self.assertEqual(response.status_code, 404)
        self.assertIn('no longer exists', response.json()['error'])

    def test_only_author_can_delete(self):
        post = SportPost.objects.create(author=self.alice, sport='Drill', text='Rondo')
        self.login(self.bob)
        self.assertEqual(self.send('delete', f'/sports/api/posts/{post.id}/').status_code, 403)
        self.login(self.alice)
        self.assertEqual(self.send('delete', f'/sports/api/posts/{post.id}/').status_code, 200)
        self.assertFalse(SportPost.objects.exists())

    def test_posting_is_rate_limited(self):
        self.login(self.alice)
        limit = views.LIMITS['post'][0]
        codes = [self.send('post', '/sports/api/posts/', {'sport': 'Padel', 'text': f'x{i}'}).status_code
                 for i in range(limit + 1)]
        self.assertEqual(codes[:limit], [201] * limit)
        self.assertEqual(codes[-1], 429)


class StickerAndCommentTests(ApiTestCase):
    def test_sticker_toggles_and_only_sport_stickers_allowed(self):
        post = SportPost.objects.create(author=self.alice, sport='Running', text='10k')
        self.login(self.bob)
        url = f'/sports/api/posts/{post.id}/sticker/'
        data = self.send('post', url, {'sticker': 'watch'}).json()['post']
        self.assertEqual((data['stickers'], data['mine'], data['top']), (1, 'watch', ['watch']))
        data = self.send('post', url, {'sticker': 'fire'}).json()['post']
        self.assertEqual((data['stickers'], data['mine']), (1, 'fire'))
        data = self.send('post', url, {'sticker': 'fire'}).json()['post']
        self.assertEqual((data['stickers'], data['mine']), (0, None))
        self.assertEqual(self.send('post', url, {'sticker': 'net'}).status_code, 400)
        self.assertEqual(self.send('post', url, raw='[1]').status_code, 400)
        self.assertEqual(PostSticker.objects.count(), 0)

    def test_comments_reactions_and_deleting_comments(self):
        post = SportPost.objects.create(author=self.alice, sport='Football', text='Goal')
        self.login(self.bob)
        self.send('post', f'/sports/api/posts/{post.id}/sticker/', {'sticker': 'fire'})
        data = self.send('post', f'/sports/api/posts/{post.id}/comments/', {'text': 'What a strike'}).json()
        self.assertEqual([c['text'] for c in data['comments']], ['What a strike'])
        self.assertEqual(data['reactions'], [{'user': {'id': self.bob.id, 'name': 'Bob', 'ini': 'B'}, 'sticker': 'fire'}])
        self.assertEqual(self.feed()['posts'][0]['comments'], 1)
        comment_id = data['comments'][0]['id']
        self.login(self.alice)  # the post's author may remove comments on it
        self.assertEqual(self.send('delete', f'/sports/api/comments/{comment_id}/').status_code, 200)
        self.assertEqual(self.send('post', f'/sports/api/posts/{post.id}/comments/', raw='{"text":5}').status_code, 400)


class EventTests(ApiTestCase):
    def make_event(self, capacity=2):
        self.login(self.alice)
        at = (timezone.now() + timedelta(days=2)).isoformat()
        response = self.send('post', '/sports/api/posts/', {
            'sport': 'Padel', 'kind': 'event', 'text': 'Saturday doubles', 'event_at': at,
            'place': 'Court 3', 'capacity': capacity})
        self.assertEqual(response.status_code, 201)
        return response.json()['post']

    def test_event_has_organiser_going_and_a_waitlist(self):
        event = self.make_event(capacity=2)
        self.assertEqual((event['event']['going_count'], event['event']['me']), (1, 'in'))
        carol = make_user('carol@example.com', 'Carol')
        self.login(self.bob)
        data = self.send('post', f"/sports/api/posts/{event['id']}/rsvp/", {'going': True}).json()['post']
        self.assertEqual((data['event']['going_count'], data['event']['me']), (2, 'in'))
        self.login(carol)
        data = self.send('post', f"/sports/api/posts/{event['id']}/rsvp/", {'going': True}).json()['post']
        self.assertEqual((data['event']['waitlist_count'], data['event']['me']), (1, 'waitlist'))
        self.login(self.bob)  # Bob drops out, Carol moves up
        self.send('post', f"/sports/api/posts/{event['id']}/rsvp/", {'going': False})
        self.login(carol)
        data = self.client.get('/sports/api/posts/').json()['posts'][0]
        self.assertEqual((data['event']['me'], data['event']['waitlist_count']), ('in', 0))

    def test_event_validation(self):
        self.login(self.alice)
        base = {'sport': 'Padel', 'kind': 'event', 'text': 'x'}
        past = (timezone.now() - timedelta(days=2)).isoformat()
        for extra in ({}, {'event_at': 'tomorrow'}, {'event_at': past},
                      {'event_at': (timezone.now() + timedelta(days=1)).isoformat(), 'capacity': 1}):
            self.assertEqual(self.send('post', '/sports/api/posts/', {**base, **extra}).status_code, 400, extra)

    def test_rsvp_only_on_events(self):
        post = SportPost.objects.create(author=self.alice, sport='Padel', text='not an event')
        self.login(self.bob)
        self.assertEqual(self.send('post', f'/sports/api/posts/{post.id}/rsvp/', {'going': True}).status_code, 400)
        self.assertFalse(EventRSVP.objects.exists())


class SocialTests(ApiTestCase):
    def test_follow_and_following_feed(self):
        SportPost.objects.create(author=self.alice, sport='Running', text='from alice')
        SportPost.objects.create(author=self.bob, sport='Running', text='from bob')
        self.login(self.bob)
        self.assertEqual(self.send('post', f'/sports/api/users/{self.bob.id}/follow/').status_code, 400)
        self.assertTrue(self.send('post', f'/sports/api/users/{self.alice.id}/follow/').json()['following'])
        self.assertEqual([p['text'] for p in self.feed('?following=1')['posts']], ['from alice'])
        profile = self.client.get(f'/sports/api/users/{self.alice.id}/').json()
        self.assertEqual((profile['followers'], profile['i_follow'], profile['posts']), (1, True, 1))

    def test_saved_posts(self):
        post = SportPost.objects.create(author=self.alice, sport='Drill', text='keep this drill')
        self.login(self.bob)
        self.assertTrue(self.send('post', f'/sports/api/posts/{post.id}/save/').json()['saved'])
        self.assertTrue(self.feed()['posts'][0]['saved'])
        self.assertEqual(len(self.feed('?saved=1')['posts']), 1)
        self.assertFalse(self.send('post', f'/sports/api/posts/{post.id}/save/').json()['saved'])
        self.assertEqual(self.feed('?saved=1')['posts'], [])

    def test_notifications(self):
        post = SportPost.objects.create(author=self.alice, sport='Football', text='my goal')
        self.login(self.bob)
        self.send('post', f'/sports/api/posts/{post.id}/sticker/', {'sticker': 'net'})
        self.send('post', f'/sports/api/posts/{post.id}/comments/', {'text': 'nice'})
        self.send('post', f'/sports/api/users/{self.alice.id}/follow/')
        self.login(self.alice)
        self.assertEqual(self.client.get('/sports/api/me/').json()['unread'], 3)
        data = self.client.get('/sports/api/notifications/').json()
        self.assertEqual(sorted(i['type'] for i in data['items']), ['comment', 'follow', 'sticker'])
        self.send('post', '/sports/api/notifications/seen/')
        self.assertEqual(self.client.get('/sports/api/me/').json()['unread'], 0)


class SafeRedirectTests(TestCase):
    def test_login_ignores_offsite_next(self):
        make_user('dana@example.com')
        response = self.client.post('/accounts/login/?next=https://evil.example/x',
                                    {'username': 'dana@example.com', 'password': 'pw-for-tests-only'})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('evil.example', response['Location'])

    def test_login_keeps_onsite_next(self):
        make_user('erik@example.com')
        response = self.client.post('/accounts/login/?next=/sports/',
                                    {'username': 'erik@example.com', 'password': 'pw-for-tests-only'})
        self.assertEqual(response['Location'], '/sports/')
