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
        # Home feed: your own posts plus people you follow, newest first.
        self.assertEqual([p['text'] for p in self.feed('?following=1')['posts']], ['from bob', 'from alice'])
        profile = self.client.get(f'/sports/api/users/{self.alice.id}/').json()
        self.assertEqual((profile['followers'], profile['i_follow'], profile['posts']), (1, True, 1))

    def test_home_feed_hides_people_you_dont_follow(self):
        SportPost.objects.create(author=self.alice, sport='Padel', text='alice padel')
        self.login(self.bob)
        self.assertEqual(self.feed('?following=1')['posts'], [])
        self.send('post', f'/sports/api/users/{self.alice.id}/follow/')
        self.assertEqual(len(self.feed('?following=1')['posts']), 1)

    def test_suggested_players(self):
        self.assertEqual(self.client.get('/sports/api/users/suggested/').status_code, 401)
        SportPost.objects.create(author=self.alice, sport='Padel', text='alice padel')
        SportPost.objects.create(author=self.bob, sport='Running', text='bob run')
        self.login(self.bob)
        d = self.client.get('/sports/api/users/suggested/').json()
        self.assertEqual([u['user']['id'] for u in d['users']], [self.alice.id])
        self.assertEqual((d['users'][0]['sports'], d['following']), (['Padel'], 0))
        self.send('post', f'/sports/api/users/{self.alice.id}/follow/')
        d = self.client.get('/sports/api/users/suggested/').json()
        self.assertEqual((d['users'], d['following']), ([], 1))

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


class GameManagementTests(ApiTestCase):
    def game(self, capacity=2, days=2):
        return SportPost.objects.create(author=self.alice, sport='Padel', kind='event', text='Doubles',
                                        event_at=timezone.now() + timedelta(days=days), capacity=capacity)

    def join(self, user, post, going=True):
        self.login(user)
        return self.send('post', f'/sports/api/posts/{post.id}/rsvp/', {'going': going})

    def notice_types(self, user):
        self.login(user)
        return [i['type'] for i in self.client.get('/sports/api/notifications/').json()['items']]

    def test_promotion_from_waitlist_is_notified_and_position_shown(self):
        post = self.game(capacity=1)
        EventRSVP.objects.create(post=post, user=self.alice)
        carol = make_user('carol@example.com', 'Carol')
        data = self.join(self.bob, post).json()['post']['event']
        self.assertEqual((data['me'], data['waitlist_position']), ('waitlist', 1))
        data = self.join(carol, post).json()['post']['event']
        self.assertEqual(data['waitlist_position'], 2)
        self.assertEqual(self.join(self.alice, post, going=False).status_code, 400)  # organiser can't leave
        post.capacity = 2
        post.save()  # simulate a spot freeing without an edit: Bob is in now
        self.join(carol, post, going=False)
        self.assertIn('waitlisted', self.notice_types(self.alice))
        self.assertIn('left', self.notice_types(self.alice))

    def test_leaving_promotes_next_person_with_notice(self):
        post = self.game(capacity=2)
        EventRSVP.objects.create(post=post, user=self.alice)
        carol = make_user('carol@example.com', 'Carol')
        self.join(self.bob, post)
        self.join(carol, post)  # waitlisted
        self.join(self.bob, post, going=False)
        self.assertIn('promoted', self.notice_types(carol))

    def test_cancel_notifies_and_blocks_rsvps(self):
        post = self.game()
        EventRSVP.objects.create(post=post, user=self.alice)
        self.join(self.bob, post)
        self.login(self.bob)
        self.assertEqual(self.send('post', f'/sports/api/posts/{post.id}/cancel/').status_code, 403)
        self.login(self.alice)
        data = self.send('post', f'/sports/api/posts/{post.id}/cancel/').json()['post']
        self.assertTrue(data['event']['cancelled'])
        self.assertIn('cancelled', self.notice_types(self.bob))
        self.assertEqual(self.join(self.bob, post).status_code, 400)
        self.assertEqual(self.client.get('/sports/api/posts/?upcoming=1').json()['posts'], [])

    def test_edit_game_notifies_and_guards_capacity(self):
        post = self.game(capacity=3)
        EventRSVP.objects.create(post=post, user=self.alice)
        self.join(self.bob, post)
        self.login(self.bob)
        self.assertEqual(self.send('patch', f'/sports/api/posts/{post.id}/', {'text': 'mine now'}).status_code, 403)
        self.login(self.alice)
        self.assertEqual(self.send('patch', f'/sports/api/posts/{post.id}/', {'capacity': 1}).status_code, 400)
        new_at = (timezone.now() + timedelta(days=3)).isoformat()
        data = self.send('patch', f'/sports/api/posts/{post.id}/', {'event_at': new_at, 'place': 'Court 9'}).json()['post']
        self.assertEqual((data['event']['place'], data['edited']), ('Court 9', True))
        self.assertIn('changed', self.notice_types(self.bob))

    def test_no_leaving_after_start_and_no_games_in_the_past(self):
        post = self.game()
        self.join(self.bob, post)
        SportPost.objects.filter(pk=post.pk).update(event_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.join(self.bob, post, going=False).status_code, 400)
        self.login(self.alice)
        past = (timezone.now() - timedelta(minutes=30)).isoformat()
        r = self.send('post', '/sports/api/posts/', {'sport': 'Padel', 'kind': 'event', 'text': 'x', 'event_at': past})
        self.assertEqual(r.status_code, 400)

    def test_upcoming_is_soonest_first_and_single_post_is_shareable(self):
        later, sooner = self.game(days=5), self.game(days=1)
        ids = [p['id'] for p in self.client.get('/sports/api/posts/?upcoming=1').json()['posts']]
        self.assertEqual(ids, [sooner.id, later.id])
        self.assertEqual(self.client.get(f'/sports/api/posts/{later.id}/').json()['post']['id'], later.id)

    def test_impossible_dates_and_odd_numbers_are_400_not_500(self):
        self.login(self.alice)
        for at in ('2026-13-45T10:00', '2026-02-30T10:00:00', '2026-05-01T25:00', '2026-05-01T10:00+99:00'):
            body = {'sport': 'Padel', 'kind': 'event', 'text': 'x', 'event_at': at}
            self.assertEqual(self.send('post', '/sports/api/posts/', body).status_code, 400, at)
        for q in ('?author=%C2%B2', '?before=%C2%B2', '?author=99999999999999999999999'):
            self.assertEqual(self.client.get('/sports/api/posts/' + q).status_code, 200, q)

    def test_deleted_cursor_does_not_repeat_page_one(self):
        posts = [SportPost.objects.create(author=self.alice, sport='Padel', text=f'p{i}') for i in range(3)]
        cursor = posts[1].id
        posts[1].delete()
        ids = [p['id'] for p in self.client.get(f'/sports/api/posts/?before={cursor}').json()['posts']]
        self.assertEqual(ids, [posts[0].id])

    def test_names_never_come_from_email(self):
        nameless = get_user_model().objects.create_user(username='zed@secret.example', email='zed@secret.example',
                                                        password='pw-for-tests-only')
        self.assertEqual(self.client.get(f'/sports/api/users/{nameless.id}/').json()['user']['name'], 'Player')


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
