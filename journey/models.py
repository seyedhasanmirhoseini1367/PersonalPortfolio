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


class LearnerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_profile')
    helper_language = models.CharField(max_length=8, choices=HELPER_LANGUAGES, blank=True, default='',
                                       help_text='Optional second language shown next to English.')
    # The town (journey.town_decor, /learn/town/). Rows from the old character editor and town game are
    # ignored: only known keys are read.
    avatar = models.JSONField(default=dict, blank=True, help_text='{"sprite": 0-5}: the character in the town')
    town = models.JSONField(default=dict, blank=True, help_text='{"town_owned": [...]}: decorations bought for the town')

    def __str__(self):
        return f'{self.user} ({self.helper_language or "English only"})'

    @classmethod
    def for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    @classmethod
    def language_of(cls, user):
        if not user.is_authenticated:
            return ''
        return cls.objects.filter(user=user).values_list('helper_language', flat=True).first() or ''

# No 0/O or 1/I/L, so a code read aloud in class is typed right.
CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def new_invite_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))


LEVELS = [('', 'Not set'), ('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'),
          ('A1', 'A1'), ('A2', 'A2'), ('B1', 'B1'), ('B2', 'B2'), ('C1', 'C1')]


class StudyGroup(models.Model):
    """A place lessons live in. Personal (a private learning space, one owner) or a shared group with an invite code."""
    name = models.CharField(max_length=80)
    is_personal = models.BooleanField(default=False, help_text='A private learning space: nobody can join it.')
    level = models.CharField(max_length=12, choices=LEVELS, blank=True, default='',
                             help_text='Tells the AI who the lessons are for, e.g. A1 or beginner.')
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
        return subjects.display(self.subject)

    def is_member(self, user):
        return user.is_authenticated and self.memberships.filter(user=user).exists()

    def is_owner(self, user):
        return user.is_authenticated and self.memberships.filter(user=user, role=Membership.OWNER).exists()

    @property
    def kind_label(self):
        return 'Space' if self.is_personal else 'Group'


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
    EMPTY, PROCESSING, DRAFT, PUBLISHED, FAILED = 'empty', 'processing', 'draft', 'published', 'failed'
    STATUSES = [(EMPTY, 'Needs material'), (PROCESSING, 'Building'), (DRAFT, 'To check'), (PUBLISHED, 'Ready'),
                (FAILED, 'Failed')]
    # The steps a lesson goes through, as shown on its page.
    STEPS = ['Add material', 'Build', 'Check', 'Practise']
    SOURCE_KINDS = [('text', 'Text'), ('photos', 'Photos'), ('pdf', 'PDF'), ('docx', 'Word document'), ('mixed', 'Mixed')]

    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='packs')
    title = models.CharField(max_length=120)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_packs')
    status = models.CharField(max_length=12, choices=STATUSES, default=EMPTY)
    progress_note = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    image_count = models.PositiveSmallIntegerField(default=0)
    source_text = models.TextField(blank=True, help_text='The lesson text, typed in or read from the photos.')
    source_kind = models.CharField(max_length=8, choices=SOURCE_KINDS, blank=True, default='')
    source_parts = models.JSONField(default=list, blank=True,
                                    help_text='Where each part of source_text came from: [["Page 2", start offset], ...].')
    focus = models.CharField(max_length=200, blank=True, help_text='Optional: what the learner wants from this material.')
    attempts = models.PositiveSmallIntegerField(default=0, help_text='Build attempts by the background worker.')
    started_at = models.DateTimeField(null=True, blank=True, help_text='When the worker last took this build.')
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

    @property
    def step(self):
        """Index into STEPS of where the lesson is now."""
        return {self.EMPTY: 0, self.FAILED: 0, self.PROCESSING: 1, self.DRAFT: 2, self.PUBLISHED: 3}[self.status]

    def part_at(self, offset):
        label = ''
        for name, start in self.source_parts or []:
            if start <= offset:
                label = name
        return label

    def publish(self):
        self.status = self.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at'])


class PendingUpload(models.Model):
    """A file waiting for the background build. Deleted as soon as its text is read: originals are not kept."""
    pack = models.ForeignKey(LessonPack, on_delete=models.CASCADE, related_name='uploads')
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8)   # image, pdf, docx: a key in journey.extract.EXTRACTORS
    name = models.CharField(max_length=160, blank=True)
    data = models.BinaryField()

    class Meta:
        ordering = ['order', 'pk']


class StudyItem(models.Model):
    WORD, SENTENCE, PHRASE, GRAMMAR, QUESTION, TABLE = 'word', 'sentence', 'phrase', 'grammar', 'question', 'table'
    CONCEPT, NOTE = 'concept', 'note'
    KINDS = [(WORD, 'Word'), (SENTENCE, 'Sentence'), (PHRASE, 'Useful phrase'),
             (GRAMMAR, 'Grammar note'), (QUESTION, 'Comprehension question'), (TABLE, 'Inflection table'),
             (CONCEPT, 'Concept'), (NOTE, 'Key idea')]
    # Kinds that go into the daily spaced-repetition review.
    REVIEWABLE = (WORD, SENTENCE, PHRASE, CONCEPT, QUESTION, TABLE)   # a table is practised one form at a time

    HIGH, MEDIUM, LOW = 'high', 'medium', 'low'
    CONFIDENCE = [(HIGH, 'Verified'), (MEDIUM, 'Needs review'), (LOW, 'Low confidence')]

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
    source_ref = models.CharField(max_length=60, blank=True, help_text='Where in the material it came from, e.g. Page 3.')

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


class ReviewLog(models.Model):
    """One answer in practice. Kept so progress can tell recognising something from producing it."""
    FLASH, TYPE, CHOICE = 'flash', 'type', 'choice'
    MODES = [(FLASH, 'Flashcard'), (TYPE, 'Typed answer'), (CHOICE, 'Multiple choice')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_reviews')
    item = models.ForeignKey(StudyItem, on_delete=models.CASCADE, related_name='reviews')
    grade = models.PositiveSmallIntegerField()
    mode = models.CharField(max_length=8, choices=MODES, default=FLASH)
    correct = models.BooleanField(null=True, help_text='Checked by the app (typed or chosen); empty for self-graded cards.')
    verified = models.BooleanField(default=False, help_text='The server checked the answer itself (rewards trust only these).')
    scheduled = models.BooleanField(default=False, help_text='The card was due by the schedule (not an extra round).')
    first = models.BooleanField(default=False, help_text='The first answer ever on this card.')
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'at'])]


class RewardEvent(models.Model):
    """The ledger of XP and coins. Every reward is one row; `key` makes each reward happen at most once.

    Balances are sums over this table, so every point can be traced to the learning that earned it.
    """
    ANSWER, LESSON, QUEST, ACHIEVEMENT, LEVEL, PURCHASE = 'answer', 'lesson', 'quest', 'achievement', 'level', 'purchase'
    SCENE = 'scene'
    KINDS = [(ANSWER, 'Answer'), (LESSON, 'Lesson complete'), (QUEST, 'Quest'), (ACHIEVEMENT, 'Achievement'),
             (LEVEL, 'Level up'), (PURCHASE, 'Purchase'), (SCENE, 'Conversation')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_rewards')
    kind = models.CharField(max_length=12, choices=KINDS)
    key = models.CharField(max_length=80, help_text='e.g. answer:<item>:<day>, quest:<pk>, achievement:<code>')
    xp = models.IntegerField(default=0)
    coins = models.IntegerField(default=0, help_text='Negative for a purchase.')
    group = models.ForeignKey(StudyGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.CharField(max_length=160, blank=True)
    day = models.DateField(help_text='Local date it was earned.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'key'], name='journey_reward_once')]
        indexes = [models.Index(fields=['user', 'day'])]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} {self.key}: {self.xp} XP, {self.coins} coins'


class Quest(models.Model):
    """A daily or weekly goal, picked by fixed rules from the learner's own cards. Progress is counted from ReviewLog."""
    DAY, WEEK = 'day', 'week'
    PERIODS = [(DAY, 'Daily'), (WEEK, 'Weekly')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_quests')
    period = models.CharField(max_length=4, choices=PERIODS, default=DAY)
    starts = models.DateField(help_text='The day, or the Monday of the week.')
    code = models.CharField(max_length=24)
    title = models.CharField(max_length=120)
    detail = models.CharField(max_length=200, blank=True, help_text='Why this quest helps.')
    target = models.PositiveSmallIntegerField()
    xp = models.PositiveSmallIntegerField(default=0)
    coins = models.PositiveSmallIntegerField(default=0)
    group = models.ForeignKey(StudyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'period', 'starts', 'code'], name='journey_quest_once')]
        ordering = ['period', 'pk']

    def __str__(self):
        return f'{self.user} {self.starts} {self.title}'


class Achievement(models.Model):
    """An unlocked achievement. What each code means lives in journey.game.ACHIEVEMENTS."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journey_achievements')
    code = models.CharField(max_length=24)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'code'], name='journey_achievement_once')]
        ordering = ['-unlocked_at']


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
    """Not used since the role-play pages were removed; kept so stored rows are not dropped.

    A short role-play built from a lesson: the learner plays one role in a dialogue.

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
