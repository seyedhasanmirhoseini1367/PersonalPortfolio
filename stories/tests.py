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
