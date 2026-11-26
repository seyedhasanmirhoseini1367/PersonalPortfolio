import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import pipeline, srs
from .models import LessonPack, Membership, Progress, StudyGroup, StudyItem

User = get_user_model()

TEXT = ('Minä asun Tampereella. Asuntoni on pieni, mutta valoisa. '
        'Keittiössä on pöytä ja kaksi tuolia. Juon aamulla kahvia keittiössä.')

LING = {
    'words': [
        {'lemma': 'asua', 'form_in_text': 'asun', 'pos': 'verb', 'grammar': 'verbityyppi 1',
         'meaning_fa': 'زندگی کردن', 'meaning_en': 'to live', 'example': 'Minä asun Tampereella.'},
        {'lemma': 'keittiö', 'form_in_text': 'keittiössä', 'pos': 'noun', 'grammar': 'inessiivi (in)',
         'meaning_fa': 'آشپزخانه', 'meaning_en': 'kitchen', 'example': 'Keittiössä on pöytä ja kaksi tuolia.'},
        {'lemma': 'kahvi', 'form_in_text': 'kahvia', 'pos': 'noun', 'grammar': 'partitiivi',
         'meaning_fa': 'قهوه', 'meaning_en': '', 'example': 'An invented sentence not in the text.'},
        {'lemma': 'lentokone', 'form_in_text': 'lentokoneessa', 'pos': 'noun', 'grammar': '',
         'meaning_fa': 'هواپیما', 'meaning_en': 'aeroplane', 'example': ''},
        {'lemma': 'asua', 'form_in_text': 'asun', 'meaning_en': 'duplicate'},
        {'lemma': '2026'},
    ],
    'sentences': [
        {'sentence': 'Juon aamulla kahvia keittiössä.', 'cloze': 'kahvia', 'meaning_en': 'I drink coffee in the morning in the kitchen.'},
        {'sentence': 'This sentence is not in the lesson.', 'cloze': 'sentence'},
        {'sentence': 'Asuntoni on pieni, mutta valoisa.', 'cloze': 'iso'},
    ],
}

TEACH = {
    'summary_fa': 'این درس درباره‌ی خانه است.',
    'grammar': [{'title': 'Inessiivi: -ssa / -ssä', 'explanation_fa': 'یعنی «در»',
                 'examples': ['Keittiössä on pöytä ja kaksi tuolia.', 'Not from the text.']}],
    'phrases': [{'fi': 'Asun Tampereella.', 'meaning_en': 'I live in Tampere.'}, {'fi': 'asun tampereella.'}],
    'questions': [
        {'question': 'Missä minä asun?', 'options': ['Helsingissä', 'Tampereella', 'Turussa', 'Oulussa'], 'answer': 1},
        {'question': 'Broken', 'options': ['a', 'a', 'b', 'c'], 'answer': 0},
        {'question': 'Bad answer', 'options': ['a', 'b', 'c', 'd'], 'answer': 7},
    ],
    'tables': [
        {'lemma': 'asua', 'meaning_en': 'to live', 'rows': [['minä', 'asun'], ['sinä', 'asut'], ['hän', 'asuu'],
                                                            ['me', 'asumme'], ['te', 'asutte'], ['he', 'asuvat']]},
        {'lemma': 'olla', 'rows': [['minä', 'olen']]},
    ],
}


def fake_lookup(lemma, session=None):
    return {'asua': (True, 'to live'), 'keittiö': (True, 'kitchen'), 'kahvi': (True, 'coffee')}.get(lemma, (False, ''))


def png_bytes():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (40, 60), 'white').save(out, format='PNG')
    return out.getvalue()


class SrsTests(TestCase):
    def setUp(self):
        self.p = Progress(ease=2.5, interval=0, reps=0, lapses=0)

    def test_intervals_grow(self):
        now = timezone.now()
        srs.schedule(self.p, srs.GOOD, now)
        self.assertEqual(self.p.interval, 1)
        srs.schedule(self.p, srs.GOOD, now)
        self.assertEqual(self.p.interval, 6)
        srs.schedule(self.p, srs.GOOD, now)
        self.assertGreaterEqual(self.p.interval, 15)
        self.assertEqual(self.p.due.date(), (now + timedelta(days=self.p.interval)).date())

    def test_forgetting_resets_and_counts_a_lapse(self):
        srs.schedule(self.p, srs.GOOD)
        srs.schedule(self.p, srs.AGAIN)
        self.assertEqual((self.p.reps, self.p.interval, self.p.lapses), (0, 0, 1))
        self.assertLess(self.p.due, timezone.now() + timedelta(hours=1))

    def test_first_again_is_not_a_lapse_and_ease_has_a_floor(self):
        for _ in range(10):
            srs.schedule(self.p, srs.AGAIN)
        self.assertEqual(self.p.lapses, 0)
        self.assertGreaterEqual(self.p.ease, 1.3)


class QualityTests(TestCase):
    def test_words_are_grounded_and_deduplicated(self):
        words = pipeline.clean_words(LING['words'], TEXT)
        self.assertEqual([w['lemma'] for w in words], ['asua', 'keittiö', 'kahvi', 'lentokone'])
        kahvi = words[2]
        self.assertEqual(kahvi['example'], '', 'an example that is not in the text is dropped')
        self.assertTrue(kahvi['grounded'])
        self.assertFalse(words[3]['grounded'], 'a form the text does not contain is flagged')

    def test_sentences_must_be_in_text_with_a_real_cloze(self):
        sentences = pipeline.clean_sentences(LING['sentences'], TEXT)
        self.assertEqual([s['cloze'] for s in sentences], ['kahvia'])

    def test_questions_need_four_distinct_options_and_a_valid_answer(self):
        self.assertEqual([q['question'] for q in pipeline.clean_questions(TEACH['questions'])], ['Missä minä asun?'])

    def test_grammar_examples_tables_and_phrases(self):
        g = pipeline.clean_grammar(TEACH['grammar'], TEXT)
        self.assertEqual(g[0]['examples'], ['Keittiössä on pöytä ja kaksi tuolia.'])
        self.assertEqual([t['lemma'] for t in pipeline.clean_tables(TEACH['tables'], TEXT)], ['asua'])
        self.assertEqual(len(pipeline.clean_phrases(TEACH['phrases'])), 1)

    def test_checker_grades_confidence(self):
        words = pipeline.check_words(pipeline.clean_words(LING['words'], TEXT), fake_lookup)
        by = {w['lemma']: w for w in words}
        self.assertEqual(by['asua']['confidence'], StudyItem.HIGH)
        self.assertEqual(by['kahvi']['meaning_en'], 'coffee', 'an empty English meaning is filled from Wiktionary')
        self.assertEqual(by['lentokone']['confidence'], StudyItem.LOW)

    def test_wiktionary_network_error_is_not_a_verdict(self):
        import requests
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError
        self.assertEqual(pipeline.wiktionary_lookup('talo', session), (None, ''))


def patched_pipeline():
    return mock.patch.multiple(pipeline, linguist=mock.Mock(return_value=LING), teacher=mock.Mock(return_value=TEACH),
                               read_images=mock.Mock(return_value=TEXT), wiktionary_lookup=fake_lookup)


@override_settings(JOURNEY_RUN_INLINE=True)
class FlowTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user('hasan', 'h@example.test', 'pw-hasan-123!')
        self.friend = User.objects.create_user('friend', 'f@example.test', 'pw-friend-123!')
        self.stranger = User.objects.create_user('stranger', 's@example.test', 'pw-stranger-123!')
        self.client.force_login(self.me)
        self.client.post(reverse('journey:group_create'), {'name': 'Suomi A1'})
        self.group = StudyGroup.objects.get()

    def _make_pack(self, **extra):
        data = {'title': 'Kappale 3', 'text': TEXT, **extra}
        with patched_pipeline():
            r = self.client.post(reverse('journey:pack_new', args=[self.group.invite_code]), data)
        return r, LessonPack.objects.order_by('-pk').first()

    def test_login_is_required(self):
        self.client.logout()
        r = self.client.get(reverse('journey:home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])

    def test_group_creator_is_owner_and_others_join_by_code(self):
        self.assertTrue(self.group.is_owner(self.me))
        self.client.force_login(self.friend)
        r = self.client.post(reverse('journey:group_join'), {'code': self.group.invite_code.lower()})
        self.assertRedirects(r, self.group.get_absolute_url())
        self.assertTrue(self.group.is_member(self.friend))
        self.assertFalse(self.group.is_owner(self.friend))

    def test_strangers_cannot_see_a_group(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.group.get_absolute_url()).status_code, 404)

    def test_text_becomes_a_draft_pack(self):
        r, pack = self._make_pack()
        self.assertRedirects(r, pack.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(pack.status, LessonPack.DRAFT, pack.error)
        kinds = list(pack.items.values_list('kind', flat=True))
        for kind in ('word', 'sentence', 'phrase', 'grammar', 'question', 'table'):
            self.assertIn(kind, kinds)
        word = pack.items.get(kind='word', front='keittiö')
        self.assertEqual(word.confidence, StudyItem.HIGH)
        self.assertEqual(word.form_in_text, 'keittiössä')
        self.assertIn('inessiivi', word.grammar)
        self.assertEqual(pack.summary, TEACH['summary_fa'])
        # The draft review page renders for the author.
        self.assertContains(self.client.get(pack.get_absolute_url()), 'Save and publish')

    def test_photos_are_read_and_not_stored(self):
        img = SimpleUploadedFile('page1.png', png_bytes(), content_type='image/png')
        with patched_pipeline():
            self.client.post(reverse('journey:pack_new', args=[self.group.invite_code]),
                             {'title': 'From photos', 'images': [img]})
        pack = LessonPack.objects.get(title='From photos')
        self.assertEqual(pack.status, LessonPack.DRAFT, pack.error)
        self.assertEqual(pack.image_count, 1)
        self.assertIn('Tampereella', pack.source_text)

    def test_empty_or_over_limit_uploads_are_refused(self):
        r = self.client.post(reverse('journey:pack_new', args=[self.group.invite_code]), {'title': 'Empty', 'text': 'short'})
        self.assertEqual(r.status_code, 400)
        with override_settings():
            from . import views
            with mock.patch.object(views, 'DAILY_PACKS', 0):
                r = self.client.post(reverse('journey:pack_new', args=[self.group.invite_code]), {'title': 'X', 'text': TEXT})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(LessonPack.objects.exists())

    def test_ai_failure_leaves_a_failed_pack_with_a_reason(self):
        with mock.patch.object(pipeline, 'linguist', side_effect=RuntimeError('quota exceeded')), \
             mock.patch.object(pipeline, 'teacher', return_value={}):
            self.client.post(reverse('journey:pack_new', args=[self.group.invite_code]), {'title': 'Fails', 'text': TEXT})
        pack = LessonPack.objects.get(title='Fails')
        self.assertEqual(pack.status, LessonPack.FAILED)
        self.assertIn('quota exceeded', pack.error)
        self.assertContains(self.client.get(pack.get_absolute_url()), 'Try again')

    def test_edit_publish_then_the_group_reviews(self):
        _, pack = self._make_pack()
        word = pack.items.get(kind='word', front='lentokone')
        self.assertEqual(word.confidence, StudyItem.LOW)
        junk = pack.items.get(kind='phrase')
        # Friend joins but cannot see the draft yet.
        Membership.objects.create(group=self.group, user=self.friend)
        self.client.force_login(self.friend)
        self.assertNotContains(self.client.get(pack.get_absolute_url()), 'Save and publish')
        self.assertEqual(self.client.post(reverse('journey:pack_edit', args=[pack.pk]), {'action': 'publish'}).status_code, 404)

        self.client.force_login(self.me)
        self.client.post(reverse('journey:pack_edit', args=[pack.pk]), {
            'action': 'publish', f'{word.pk}-meaning_en': 'aeroplane (corrected)', f'{junk.pk}-delete': 'on'})
        pack.refresh_from_db()
        word.refresh_from_db()
        self.assertEqual(pack.status, LessonPack.PUBLISHED)
        self.assertEqual(word.meaning_en, 'aeroplane (corrected)')
        self.assertEqual(word.confidence, StudyItem.HIGH, 'a word a person corrected counts as checked')
        self.assertFalse(StudyItem.objects.filter(pk=junk.pk).exists())

        # Friend studies: new cards come first, grading schedules them.
        self.client.force_login(self.friend)
        self.assertContains(self.client.get(pack.get_absolute_url()), 'Check your understanding')
        cards = self.client.get(reverse('journey:api_due')).json()['cards']
        reviewable = pack.items.filter(kind__in=StudyItem.REVIEWABLE).count()
        self.assertEqual(len(cards), reviewable)
        self.assertTrue(all(c['kind'] in StudyItem.REVIEWABLE for c in cards))
        rank = {'word': 0, 'sentence': 1, 'phrase': 2}
        order = [rank[c['kind']] for c in cards]
        self.assertEqual(order, sorted(order), 'new cards: words first, then sentences, then phrases')
        first = cards[0]['id']
        r = self.client.post(reverse('journey:api_grade'), {'item': first, 'grade': 'good'})
        self.assertEqual(r.json()['interval'], 1)
        self.client.post(reverse('journey:api_grade'), {'item': first, 'grade': 'again'})
        prog = Progress.objects.get(user=self.friend, item_id=first)
        self.assertEqual(prog.lapses, 1)
        self.assertContains(self.client.get(reverse('journey:mistakes')), 'forgot 1×')
        mistakes = self.client.get(reverse('journey:api_due') + '?mode=mistakes').json()['cards']
        self.assertEqual([c['id'] for c in mistakes], [first])
        # The owner's progress is separate.
        self.assertFalse(Progress.objects.filter(user=self.me).exists())

    def test_strangers_cannot_grade_or_read_cards(self):
        _, pack = self._make_pack()
        pack.publish()
        item = pack.items.filter(kind='word').first()
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(reverse('journey:api_grade'), {'item': item.pk, 'grade': 'good'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('journey:api_due')).json()['cards'], [])
        self.assertEqual(self.client.get(pack.get_absolute_url()).status_code, 404)

    def test_new_cards_per_day_are_limited(self):
        _, pack = self._make_pack()
        pack.publish()
        from . import views
        with mock.patch.object(views, 'NEW_PER_DAY', 2):
            cards = self.client.get(reverse('journey:api_due')).json()['cards']
            self.assertEqual(len(cards), 2)
            for c in cards:
                self.client.post(reverse('journey:api_grade'), {'item': c['id'], 'grade': 'good'})
            self.assertEqual(self.client.get(reverse('journey:api_due')).json()['cards'], [])

    def test_pages_render(self):
        _, pack = self._make_pack()
        pack.publish()
        for url in (reverse('journey:home'), self.group.get_absolute_url(), reverse('journey:pack_new', args=[self.group.invite_code]),
                    pack.get_absolute_url(), reverse('journey:review'), reverse('journey:mistakes'),
                    reverse('journey:review') + f'?group={self.group.invite_code}'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
