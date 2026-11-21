from django.test import TestCase


class LearningCardTests(TestCase):
    def test_bullets_with_unsupported_numbers_are_dropped(self):
        from .summarizer import _grounded, _numbers
        known = _numbers('We used 5-fold CV and lr 0.001 with EfficientNet-B5.')
        kept = _grounded(['5-fold group CV', 'lr 0.001', 'Gained 12% from TTA', 'EfficientNet-B5 backbone', 42], known)
        self.assertEqual(kept, ['5-fold group CV', 'lr 0.001', 'EfficientNet-B5 backbone'])

    def test_competition_page_shows_cards_and_hides_raw_writeups(self):
        from .models import Competition, Solution
        comp = Competition.objects.create(name='Demo Comp', slug='demo-comp',
                                          insights={'challenge': 'Noisy labels.', 'lessons': ['Trust CV.'],
                                                    'common': [], 'distinctive': [], 'based_on': 1})
        Solution.objects.create(competition=comp, rank=1, team_name='Team A', medal='gold',
                                writeup_content='<script>alert(1)</script> secret full text',
                                writeup_url='https://www.kaggle.com/x',
                                card={'headline': 'Strong CV.', 'validation': ['5-fold group CV'], 'models': ['GBDT']})
        r = self.client.get('/kaggle-winners-archive/demo-comp/')
        self.assertEqual(r.status_code, 200)
        for text in ('What the winners did', 'Trust CV.', 'Side by side', '5-fold group CV', 'Strong CV.'):
            self.assertContains(r, text)
        self.assertNotContains(r, 'secret full text')
        self.assertNotContains(r, '<script>alert(1)')

    def test_markdown_filter_strips_scripts(self):
        from .templatetags.markdown_tags import render_markdown
        out = render_markdown('**bold** <img src=x onerror=alert(1)><script>x()</script>')
        self.assertIn('<strong>bold</strong>', out)
        self.assertNotIn('onerror', out)
        self.assertNotIn('<script', out)
