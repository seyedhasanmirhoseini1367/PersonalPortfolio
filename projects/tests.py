from django.test import TestCase


class SportsPrototypePageTests(TestCase):
    def test_sports_page_serves_the_prototype(self):
        response = self.client.get('/sports/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sports Social App', b''.join(response.streaming_content))
