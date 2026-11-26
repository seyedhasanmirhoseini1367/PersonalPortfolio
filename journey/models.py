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


# Parts a cartoon character is drawn from (static/journey/avatar.js draws them).
AVATAR_PARTS = {
    'skin': ['#f6d7c3', '#eac09a', '#d39b6a', '#a86b3c', '#6e4527'],
    'hair': ['short', 'long', 'curly', 'bun', 'bald', 'cap'],
    'hair_color': ['#2b2118', '#5a3a22', '#a5672f', '#e0b45a', '#c2c2c2', '#b8473a', '#3b5bdb'],
    'shirt': ['#2f8fd8', '#d9546b', '#3fae74', '#e0a43a', '#7c5cd6', '#33414d'],
    'extra': ['none', 'glasses', 'scarf', 'earrings', 'beard'],
}


def clean_avatar(spec, seed=''):
    """Keep only known parts; fill gaps deterministically from seed so everyone has a character."""
    spec = spec if isinstance(spec, dict) else {}
    h = sum(ord(c) * (i + 1) for i, c in enumerate(seed or 'x'))
    out = {}
    for n, (part, options) in enumerate(AVATAR_PARTS.items()):
        out[part] = spec.get(part) if spec.get(part) in options else options[(h // (n + 1)) % len(options)]
    if not spec.get('extra'):
        out['extra'] = 'none'
    return out


class LearnerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_profile')
    helper_language = models.CharField(max_length=8, choices=HELPER_LANGUAGES, blank=True, default='',
                                       help_text='Optional second language shown next to English.')
    avatar = models.JSONField(default=dict, blank=True,
                              help_text='Cartoon character: {"skin","hair","hair_color","shirt","extra"}; see AVATAR_PARTS.')
    town = models.JSONField(default=dict, blank=True,
                            help_text='Town game progress: {"coins": int, "done": {quest: stars}, "sprite": frame}.')

    def __str__(self):
        return f'{self.user} ({self.helper_language or "English only"})'

    @classmethod
    def for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    def avatar_spec(self):
        return clean_avatar(self.avatar, seed=self.user.username)

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
    subject = models.CharField(max_length=24, default='finnish',
                               help_text='Which agents build its lessons; a key in journey.subjects.SUBJECTS.')
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

    @property
    def subject_info(self):
        from . import subjects
        return subjects.get(self.subject)

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


SETTINGS = {
    # key: (label, Font Awesome icon, two backdrop colours)
    'cafe': ('Café', 'fa-mug-hot', '#f3e1cf', '#c98b5a'),
    'market': ('Market', 'fa-basket-shopping', '#e5f2dc', '#6aa84f'),
    'shop': ('Shop', 'fa-store', '#e3eefb', '#4a86c5'),
    'station': ('Station', 'fa-train', '#e7e9f2', '#5b6b9a'),
    'doctor': ('Health centre', 'fa-stethoscope', '#e3f4f4', '#3c9d9b'),
    'classroom': ('Classroom', 'fa-chalkboard-user', '#f1ecdd', '#9b7d3c'),
    'home': ('Home', 'fa-house', '#f6e4e8', '#c06a80'),
    'street': ('Street', 'fa-city', '#e6ecef', '#61788a'),
    'party': ('Party', 'fa-champagne-glasses', '#efe4f6', '#8a5cb5'),
    'office': ('Office', 'fa-briefcase', '#e4e7ea', '#56606b'),
}


class Scene(models.Model):
    """A short role-play built from a lesson: the learner plays one role in a dialogue.

    steps: [{"who": "npc", "fi": "...", "en": "..."},
            {"who": "you", "fi": "correct line", "en": "...",
             "options": ["...", "...", "..."], "answer": 0}]
    """
    pack = models.ForeignKey(LessonPack, on_delete=models.CASCADE, related_name='scenes')
    order = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=120)
    setting = models.CharField(max_length=20, default='street')
    situation_en = models.CharField(max_length=300, blank=True, help_text='One line: who you are and what happens.')
    npc_name = models.CharField(max_length=40, default='Aino')
    npc_role = models.CharField(max_length=60, blank=True)
    you_role = models.CharField(max_length=60, blank=True)
    steps = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f'{self.pack}: {self.title}'

    def get_absolute_url(self):
        return reverse('journey:scene', args=[self.pk])

    @property
    def setting_info(self):
        label, icon, light, dark = SETTINGS.get(self.setting, SETTINGS['street'])
        return {'key': self.setting if self.setting in SETTINGS else 'street', 'label': label, 'icon': icon,
                'light': light, 'dark': dark}

    @property
    def turns(self):
        return sum(1 for s in self.steps if s.get('who') == 'you')

    @property
    def max_score(self):
        return self.turns * 150


class SceneResult(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_scene_results')
    scene = models.ForeignKey(Scene, on_delete=models.CASCADE, related_name='results')
    best_score = models.PositiveIntegerField(default=0)
    best_stars = models.PositiveSmallIntegerField(default=0)
    last_score = models.PositiveIntegerField(default=0)
    plays = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'scene')]

    def __str__(self):
        return f'{self.user} · {self.scene}: {self.best_score}'
