"""LearningJourney: study groups turn lesson photos or text into lesson packs.

A group (a class) has members. A lesson pack is built once by the AI pipeline,
checked by a person, then published to the whole group. Each member keeps their
own spaced-repetition progress per item.
"""
import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

LANGUAGES = [('fi', 'Finnish')]

# English is always shown. A member may add one more language they know better.
HELPER_LANGUAGES = [
    ('', 'None (English only)'), ('ar', 'Arabic · العربية'), ('bn', 'Bengali · বাংলা'), ('zh', 'Chinese · 中文'),
    ('et', 'Estonian · Eesti'), ('tl', 'Filipino'), ('fr', 'French · Français'), ('de', 'German · Deutsch'),
    ('hi', 'Hindi · हिन्दी'), ('it', 'Italian · Italiano'), ('ja', 'Japanese · 日本語'), ('ku', 'Kurdish · Kurdî'),
    ('ne', 'Nepali · नेपाली'), ('fa', 'Persian · فارسی'), ('pl', 'Polish · Polski'), ('pt', 'Portuguese · Português'),
    ('ru', 'Russian · Русский'), ('so', 'Somali · Soomaali'), ('es', 'Spanish · Español'), ('sv', 'Swedish · Svenska'),
    ('th', 'Thai · ไทย'), ('ti', 'Tigrinya · ትግርኛ'), ('tr', 'Turkish · Türkçe'), ('uk', 'Ukrainian · Українська'),
    ('ur', 'Urdu · اردو'), ('vi', 'Vietnamese · Tiếng Việt'),
]
HELPER_NAMES = {code: name.split(' · ')[0] for code, name in HELPER_LANGUAGES if code}
RTL_LANGUAGES = {'ar', 'fa', 'ur', 'he'}


class LearnerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_profile')
    helper_language = models.CharField(max_length=8, choices=HELPER_LANGUAGES, blank=True, default='',
                                       help_text='Optional second language shown next to English.')

    def __str__(self):
        return f'{self.user} ({self.helper_language or "English only"})'

    @classmethod
    def language_of(cls, user):
        if not user.is_authenticated:
            return ''
        return cls.objects.filter(user=user).values_list('helper_language', flat=True).first() or ''

# No 0/O or 1/I/L, so a code read aloud in class is typed right.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def new_invite_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))


class StudyGroup(models.Model):
    name = models.CharField(max_length=80)
    language = models.CharField(max_length=8, choices=LANGUAGES, default='fi')
    invite_code = models.CharField(max_length=12, unique=True, default=new_invite_code)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name='journey_groups_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('journey:group', args=[self.invite_code])

    def is_member(self, user):
        return user.is_authenticated and self.memberships.filter(user=user).exists()

    def is_owner(self, user):
        return user.is_authenticated and self.memberships.filter(user=user, role=Membership.OWNER).exists()


class Membership(models.Model):
    OWNER, MEMBER = 'owner', 'member'
    ROLES = [(OWNER, 'Owner'), (MEMBER, 'Member')]

    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_memberships')
    role = models.CharField(max_length=10, choices=ROLES, default=MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('group', 'user')]
        ordering = ['joined_at']

    def __str__(self):
        return f'{self.user} in {self.group}'


class LessonPack(models.Model):
    PROCESSING, DRAFT, PUBLISHED, FAILED = 'processing', 'draft', 'published', 'failed'
    STATUSES = [(PROCESSING, 'Processing'), (DRAFT, 'Draft'), (PUBLISHED, 'Published'), (FAILED, 'Failed')]

    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='packs')
    title = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_packs')
    status = models.CharField(max_length=12, choices=STATUSES, default=PROCESSING)
    progress_note = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    image_count = models.PositiveSmallIntegerField(default=0)
    source_text = models.TextField(blank=True, help_text='The lesson text, typed in or read from the photos.')
    summary = models.TextField(blank=True, help_text='In English.')
    translations = models.JSONField(default=dict, blank=True,
                                    help_text='Summary per helper language: {"fa": "..."}; a key means the whole pack is translated.')
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('journey:pack', args=[self.pk])

    def can_edit(self, user):
        return user.is_authenticated and (user == self.created_by or self.group.is_owner(user))

    def publish(self):
        self.status = self.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at'])


class StudyItem(models.Model):
    WORD, SENTENCE, PHRASE, GRAMMAR, QUESTION, TABLE = 'word', 'sentence', 'phrase', 'grammar', 'question', 'table'
    KINDS = [(WORD, 'Word'), (SENTENCE, 'Sentence'), (PHRASE, 'Useful phrase'),
             (GRAMMAR, 'Grammar note'), (QUESTION, 'Comprehension question'), (TABLE, 'Inflection table')]
    # Kinds that go into the daily spaced-repetition review.
    REVIEWABLE = (WORD, SENTENCE, PHRASE)

    HIGH, MEDIUM, LOW = 'high', 'medium', 'low'
    CONFIDENCE = [(HIGH, 'Checked'), (MEDIUM, 'Likely'), (LOW, 'Unsure')]

    pack = models.ForeignKey(LessonPack, on_delete=models.CASCADE, related_name='items')
    kind = models.CharField(max_length=10, choices=KINDS)
    order = models.PositiveIntegerField(default=0)
    front = models.CharField(max_length=300, help_text='Base form, sentence, phrase, note title or question.')
    form_in_text = models.CharField(max_length=120, blank=True, help_text='The form seen in the lesson, e.g. talossa.')
    grammar = models.CharField(max_length=160, blank=True, help_text='Case, verb type, gradation...')
    meaning_en = models.CharField(max_length=400, blank=True, help_text='English meaning or translation.')
    example = models.CharField(max_length=400, blank=True, help_text='A sentence from the lesson.')
    body = models.TextField(blank=True, help_text='Longer English text: grammar explanation or question explanation.')
    data = models.JSONField(default=dict, blank=True, help_text='Cloze answer, quiz options, table rows.')
    translations = models.JSONField(default=dict, blank=True,
                                    help_text='Per helper language: {"fa": {"meaning": "...", "body": "..."}}')
    confidence = models.CharField(max_length=8, choices=CONFIDENCE, default=MEDIUM)

    class Meta:
        ordering = ['kind', 'order', 'pk']

    def __str__(self):
        return f'{self.get_kind_display()}: {self.front}'

    @property
    def reviewable(self):
        return self.kind in self.REVIEWABLE

    def helper(self, lang, field='meaning'):
        return ((self.translations or {}).get(lang) or {}).get(field, '') if lang else ''


class Progress(models.Model):
    """One member's spaced-repetition state for one item (SM-2)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_progress')
    item = models.ForeignKey(StudyItem, on_delete=models.CASCADE, related_name='progress')
    ease = models.FloatField(default=2.5)
    interval = models.PositiveIntegerField(default=0, help_text='Days until the next review.')
    reps = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0, help_text='Times forgotten: feeds the mistake notebook.')
    due = models.DateTimeField(default=timezone.now)
    last_reviewed = models.DateTimeField(null=True, blank=True)
    introduced_at = models.DateTimeField(auto_now_add=True, help_text='First seen: limits new cards per day.')

    class Meta:
        unique_together = [('user', 'item')]
        indexes = [models.Index(fields=['user', 'due'])]

    def __str__(self):
        return f'{self.user} · {self.item}'
