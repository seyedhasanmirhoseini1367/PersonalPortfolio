import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import PostSticker, SportPost


def make_user(email, first_name=''):
    return get_user_model().objects.create_user(
        username=email, email=email, password='pw-for-tests-only', first_name=first_name)


class SportsApiTests(TestCase):
    def setUp(self):
        self.alice = make_user('alice@example.com', 'Alice')
        self.bob = make_user('bob@example.com', 'Bob')
        self.client = Client(enforce_csrf_checks=True)

    def login(self, user):
        self.client.force_login(user)
        self.client.get('/sports/')  # sets the CSRF cookie, like the real page

    def send(self, method, url, data=None):
        token = self.client.cookies['csrftoken'].value
        return getattr(self.client, method)(url, data=json.dumps(data or {}),
                                            content_type='application/json', HTTP_X_CSRFTOKEN=token)

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

    def test_create_post_and_see_it_in_feed(self):
        self.login(self.alice)
        response = self.send('post', '/sports/api/posts/', {'sport': 'Padel', 'text': 'Great match!'})
        self.assertEqual(response.status_code, 201)
        feed = self.client.get('/sports/api/posts/').json()['posts']
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0]['author']['name'], 'Alice')
        self.assertEqual(feed[0]['text'], 'Great match!')
        self.assertTrue(feed[0]['can_delete'])

    def test_rejects_unknown_sport_and_empty_text(self):
        self.login(self.alice)
        self.assertEqual(self.send('post', '/sports/api/posts/', {'sport': 'Chess', 'text': 'x'}).status_code, 400)
        self.assertEqual(self.send('post', '/sports/api/posts/', {'sport': 'Padel', 'text': '  '}).status_code, 400)

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
        self.assertEqual(PostSticker.objects.count(), 0)

    def test_comments(self):
        post = SportPost.objects.create(author=self.alice, sport='Football', text='Goal')
        self.login(self.bob)
        url = f'/sports/api/posts/{post.id}/comments/'
        comments = self.send('post', url, {'text': 'What a strike'}).json()['comments']
        self.assertEqual([c['text'] for c in comments], ['What a strike'])
        self.assertEqual(self.client.get('/sports/api/posts/').json()['posts'][0]['comments'], 1)

    def test_only_author_can_delete(self):
        post = SportPost.objects.create(author=self.alice, sport='Drill', text='Rondo')
        self.login(self.bob)
        self.assertEqual(self.send('delete', f'/sports/api/posts/{post.id}/').status_code, 403)
        self.login(self.alice)
        self.assertEqual(self.send('delete', f'/sports/api/posts/{post.id}/').status_code, 200)
        self.assertFalse(SportPost.objects.exists())
