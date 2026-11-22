# stories/models.py - COMPLETE FIXED VERSION
from django.db import models
from PersonalPortfolio.storage import image_storage
from django.conf import settings
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinLengthValidator, MaxLengthValidator
from django.utils import timezone


# Slug prefixes of the automatic news stories (stories/digest.py).
DIGEST_PREFIXES = ('ai-ml-digest-', 'ai-weekly-', 'ai-repos-')


def digest_q():
    """Filter for the daily digests, weekly roundups and the weekly open-source radar."""
    q = models.Q()
    for prefix in DIGEST_PREFIXES:
        q |= models.Q(slug__startswith=prefix)
    return q


class Story(models.Model):
    """
    A story/blog post written by a user.
    """

    class Status(models.TextChoices):
        DRAFT = 'DF', 'Draft'
        PUBLISHED = 'PB', 'Published'
        ARCHIVED = 'AR', 'Archived'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stories',
        verbose_name='Author',
        help_text='The user who wrote this story'
    )

    title = models.CharField(
        max_length=200,
        verbose_name='Story Title',
        help_text='Enter a descriptive title (max 200 characters)',
        validators=[
            MinLengthValidator(10, message='Title must be at least 10 characters long.'),
            MaxLengthValidator(200, message='Title cannot exceed 200 characters.')
        ]
    )

    slug = models.SlugField(
        max_length=250,
        unique_for_date='published_at',
        blank=True,
        verbose_name='URL Slug',
        help_text='Auto-generated URL-friendly version of the title'
    )

    excerpt = models.TextField(
        max_length=500,
        blank=True,
        verbose_name='Short Excerpt',
        help_text='Brief summary of the story (max 500 characters)'
    )

    content = models.TextField(
        verbose_name='Story Content',
        help_text='Write your story here'
    )

    tags = models.ManyToManyField(
        'Tag',
        blank=True,
        related_name='stories',
        verbose_name='Story Tags',
        help_text='Categorize your story with relevant tags'
    )

    status = models.CharField(
        max_length=2,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Publication Status',
        help_text='Current status of the story'
    )

    featured_image = models.ImageField(
        upload_to='stories/%Y/%m/%d/',
        storage=image_storage,
        blank=True,
        null=True,
        verbose_name='Featured Image',
        help_text='Optional image to accompany the story'
    )

    read_time_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name='Estimated Read Time (minutes)',
        help_text='Auto-calculated reading time'
    )

    view_count = models.PositiveIntegerField(
        default=0,
        verbose_name='View Count',
        help_text='Number of times this story has been viewed'
    )

    is_featured = models.BooleanField(
        default=False,
        verbose_name='Featured Story',
        help_text='Mark this story as featured to highlight it'
    )

    allow_comments = models.BooleanField(
        default=True,
        verbose_name='Allow Comments',
        help_text='Enable or disable comments for this story'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created At'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Last Updated'
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Published At',
        help_text='Date and time when the story was published'
    )

    class Meta:
        verbose_name = 'Story'
        verbose_name_plural = 'Stories'
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['status']),
            models.Index(fields=['author']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['DF', 'PB', 'AR']),
                name='valid_story_status'
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author.username}"

    def save(self, *args, **kwargs):
        # Auto-generate slug if not provided
        if not self.slug:
            self.slug = slugify(self.title)

        # Set published_at when status changes to PUBLISHED
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()

        # Auto-calculate read time
        word_count = len(self.content.split())
        self.read_time_minutes = max(1, round(word_count / 200))

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.published_at:
            # The detail route is /stories/story/<slug>/ (it used to pass the
            # date too, which raised NoReverseMatch).
            return reverse('stories:story_detail', args=[self.slug])
        return reverse('stories:story_preview', args=[self.pk])

    def is_published(self):
        """Check if the story is published and available."""
        return self.status == self.Status.PUBLISHED and self.published_at is not None

    def increment_view_count(self):
        """Increment the view count atomically to prevent race conditions."""
        from django.db.models import F
        Story.objects.filter(id=self.id).update(view_count=F('view_count') + 1)
        self.refresh_from_db(fields=['view_count'])

    @property
    def likes_count(self):
        """Get the number of likes for this story."""
        return self.story_likes.count()

    def user_has_liked(self, user):
        """Check if a specific user has liked this story."""
        if user.is_authenticated:
            return self.story_likes.filter(user=user).exists()
        return False

    def like_story(self, user):
        """Add a like from a specific user."""
        if user.is_authenticated and not self.user_has_liked(user):
            StoryLike.objects.create(story=self, user=user)
            return True
        return False

    def unlike_story(self, user):
        """Remove a like from a specific user."""
        if user.is_authenticated:
            StoryLike.objects.filter(story=self, user=user).delete()
            return True
        return False

    # ── Daily AI & ML digest and weekly roundup (stories/digest.py) ─────────
    @property
    def is_digest(self):
        return (self.slug or '').startswith(DIGEST_PREFIXES)

    @property
    def is_repos(self):
        return (self.slug or '').startswith('ai-repos-')

    @property
    def is_weekly(self):
        return (self.slug or '').startswith('ai-weekly-')

    @property
    def digest_cover(self):
        """Text for the generated card cover: kicker, big line, small line."""
        from datetime import date, timedelta
        try:
            d = date.fromisoformat((self.slug or '')[-10:])
        except ValueError:
            d = (self.published_at or timezone.now()).date()
        if self.is_weekly:
            end = d + timedelta(days=6)
            return {'kicker': 'Weekly roundup', 'big': f'W{d.isocalendar()[1]}',
                    'small': f'{d.day} {d:%b} – {end.day} {end:%b}'}
        if self.is_repos:
            return {'kicker': 'Open-source radar', 'big': f'W{d.isocalendar()[1]}', 'small': f'{d:%d %b %Y}'}
        return {'kicker': 'Daily digest', 'big': f'{d:%d}', 'small': f'{d:%b %Y}'}

    @property
    def digest_overview(self):
        """For list cards: item counts per section and the first headline."""
        import html as _html
        import re as _re
        labels = {'Research papers': ('paper', 'papers'),
                  'From the labs and newsrooms': ('news item', 'news items'),
                  'Discussed on Hacker News': ('discussion', 'discussions'),
                  'Top stories of the week': ('top story', 'top stories'),
                  "Editor's picks": ('pick', 'picks'), 'Open source to try': ('repo', 'repos'),
                  'Trending on GitHub this week': ('repo', 'repos')}
        parts = _re.split(r'<h2>(.*?)</h2>', self.content or '')
        sections, lead, total = [], '', 0
        for name, body in zip(parts[1::2], parts[2::2]):
            n = body.count('<h3>')
            if not n:
                continue
            total += n
            one, many = labels.get(_html.unescape(name), ('item', 'items'))
            sections.append(f"{n} {one if n == 1 else many}")
            if not lead:
                m = _re.search(r'<h3>(.*?)</h3>', body, _re.S)
                lead = _html.unescape(_re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''
        return {'sections': sections, 'lead': lead, 'total': total}

    def get_excerpt(self):
        """Get excerpt or generate one from content (HTML stripped)."""
        import re
        def strip_html(html):
            return re.sub(r'<[^>]+>', '', html or '').strip()

        if self.excerpt:
            return strip_html(self.excerpt)
        text = strip_html(self.content)
        return (text[:200] + '...') if len(text) > 200 else text


class Tag(models.Model):
    """
    Tag for categorizing stories.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Tag Name',
        help_text='Name of the tag (max 50 characters)'
    )

    slug = models.SlugField(
        max_length=60,
        unique=True,
        verbose_name='URL Slug'
    )

    description = models.TextField(
        max_length=300,
        blank=True,
        verbose_name='Tag Description',
        help_text='Brief description of the tag'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('stories:tag_stories', args=[self.slug])


class Comment(models.Model):
    """
    Comment on a story.
    """
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='Story'
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='story_comments',
        verbose_name='Comment Author'
    )

    content = models.TextField(
        verbose_name='Comment Content',
        help_text='Write your comment here',
        validators=[MinLengthValidator(10, message='Comment must be at least 10 characters.')]
    )

    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
        verbose_name='Parent Comment'
    )

    is_approved = models.BooleanField(
        default=True,
        verbose_name='Approved',
        help_text='Approve or reject this comment'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Comment'
        verbose_name_plural = 'Comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['story', 'created_at']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on {self.story.title[:50]}"

    def is_reply(self):
        """Check if this comment is a reply to another comment."""
        return self.parent is not None


class StoryView(models.Model):
    """
    Track story views with additional information.
    """
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='story_views'
    )

    # ADDED: User field for authenticated users
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='story_views',
        verbose_name='User'
    )

    ip_address = models.GenericIPAddressField(
        verbose_name='IP Address'
    )

    user_agent = models.TextField(
        blank=True,
        verbose_name='User Agent'
    )

    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Story View'
        verbose_name_plural = 'Story Views'
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['story', 'viewed_at']),
            models.Index(fields=['story', 'user']),  # Added index for user
            models.Index(fields=['story', 'ip_address', 'viewed_at']),  # Added index for IP tracking
        ]

    def __str__(self):
        if self.user:
            return f"View by {self.user.username} on {self.story.title}"
        return f"View from {self.ip_address} on {self.story.title}"


class StoryLike(models.Model):
    """Track which users have liked which stories."""
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='story_likes'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_likes'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['story', 'user']  # Prevents duplicate likes
        verbose_name = 'Story Like'
        verbose_name_plural = 'Story Likes'
        indexes = [
            models.Index(fields=['story', 'user']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} likes {self.story.title}"


class DailyDigest(models.Model):
    """One day of the AI & ML digest (stories/digest.py)."""
    date       = models.DateField(unique=True)
    status     = models.CharField(max_length=10, default="running")  # running/done/empty/failed
    attempts   = models.PositiveSmallIntegerField(default=0)
    items      = models.PositiveSmallIntegerField(default=0)
    story      = models.ForeignKey(Story, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    log        = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Digest {self.date} ({self.status})"


class DigestItem(models.Model):
    """A source used in a digest (never repeated); kept for the weekly roundup."""
    url         = models.URLField(max_length=500, unique=True)
    title       = models.CharField(max_length=300)
    source      = models.CharField(max_length=100)
    digest_date = models.DateField()
    section     = models.CharField(max_length=10, blank=True)   # papers / news / hn
    topic       = models.CharField(max_length=40, blank=True)
    summary     = models.TextField(blank=True)
    why         = models.TextField(blank=True)
    score       = models.FloatField(default=0)
    also        = models.JSONField(default=list, blank=True, help_text="Other outlets covering the same story")
    angle       = models.CharField(max_length=40, blank=True)   # label of the "why" line, varies per item
    fa_title    = models.CharField(max_length=300, blank=True)  # Persian, for the Telegram channel
    fa_summary  = models.TextField(blank=True)

    class Meta:
        ordering = ["-digest_date"]


class NewsSource(models.Model):
    """Where the daily digest looks for news. Managed in the admin."""
    KIND_RSS, KIND_HF, KIND_HN, KIND_GITHUB = 'rss', 'hf_papers', 'hn', 'github'
    KIND_CHOICES = [(KIND_RSS, 'Website or RSS / Atom feed'), (KIND_HF, 'Hugging Face Daily Papers'),
                    (KIND_HN, 'Hacker News top stories'), (KIND_GITHUB, 'GitHub: new trending AI repos')]
    name      = models.CharField(max_length=100, unique=True)
    kind      = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_RSS)
    url       = models.URLField(max_length=500, blank=True,
                                help_text="A website or its RSS / Atom feed (the feed is found automatically)")
    ai_filter = models.BooleanField(default=False, help_text="Only keep items that mention AI / ML")
    active    = models.BooleanField(default=True)

    class Meta:
        ordering = ['kind', 'name']

    def __str__(self):
        return f"{self.name} ({'on' if self.active else 'off'})"


class WeeklyDigest(models.Model):
    """The Monday roundup of the past week's digests (stories/digest.py)."""
    week_start = models.DateField(unique=True, help_text="Monday of the week covered")
    status     = models.CharField(max_length=10, default='running')
    attempts   = models.PositiveSmallIntegerField(default=0)
    story      = models.ForeignKey(Story, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    log        = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-week_start']


class TelegramConfig(models.Model):
    """One row: which Telegram chat may approve posts (stories/telegram.py)."""
    admin_chat_id = models.BigIntegerField(null=True, blank=True)
    admin_name    = models.CharField(max_length=100, blank=True)
    link_code     = models.CharField(max_length=40, blank=True)
    bot_username  = models.CharField(max_length=100, blank=True)
    webhook_url   = models.CharField(max_length=300, blank=True)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


class TelegramPost(models.Model):
    """A digest announcement for the Telegram channel, sent only after approval."""
    PENDING, SENDING, SENT, SKIPPED, FAILED = 'pending', 'sending', 'sent', 'skipped', 'failed'
    STATUS_CHOICES = [(s, s.title()) for s in (PENDING, SENDING, SENT, SKIPPED, FAILED)]
    story              = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='telegram_posts')
    text               = models.TextField(help_text="Telegram HTML: <b>, <i>, <a href=...>")
    status             = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    error              = models.TextField(blank=True)
    review_message_id  = models.BigIntegerField(null=True, blank=True)
    channel_message_id = models.BigIntegerField(null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    sent_at            = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.story.title} ({self.status})'


class SuggestedLink(models.Model):
    """A link the editor wants in the next daily digest (an article, repo, paper...)."""
    PENDING, USED, FAILED = 'pending', 'used', 'failed'
    url         = models.URLField(max_length=500)
    note        = models.CharField(max_length=300, blank=True, help_text="Optional: what it is / why it is interesting")
    status      = models.CharField(max_length=10, default=PENDING)
    error       = models.CharField(max_length=300, blank=True)
    digest_date = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.url} ({self.status})'


class RadarConfig(models.Model):
    """One row: what the weekly Repo Radar looks for (stories/radar.py)."""
    topics   = models.CharField(max_length=500, default='rag, mlops, llm, ai-agents, llm-inference, machine-learning, kaggle, tabular',
                                help_text='GitHub topics / keywords, comma separated')
    profile  = models.TextField(default='ML/AI engineer building production ML systems: RAG assistants, LLM apps and agents, '
                                        'MLOps (deployment, monitoring, CI/CD, Azure), deep learning (EEG, time series) and '
                                        'Kaggle competitions (tabular, gradient boosting).',
                                help_text='Who the summaries are written for')
    max_items = models.PositiveSmallIntegerField(default=8)
    enabled   = models.BooleanField(default=True)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def topic_list(self):
        return [t.strip().lower() for t in (self.topics or '').split(',') if t.strip()][:12]


class RadarRepo(models.Model):
    """A GitHub repository seen by the Repo Radar, with a star snapshot for weekly growth."""
    full_name    = models.CharField(max_length=200, unique=True)
    description  = models.TextField(blank=True)
    stars        = models.PositiveIntegerField(default=0)
    checked_at   = models.DateTimeField(null=True, blank=True)
    weekly_gain  = models.IntegerField(default=0)
    what         = models.TextField(blank=True)
    why          = models.TextField(blank=True, help_text='Public line for the AI News post')
    angle        = models.CharField(max_length=40, blank=True)   # label of that line, varies per repo
    topic        = models.CharField(max_length=40, blank=True)
    try_cmd      = models.CharField(max_length=200, blank=True, help_text='Install / run command found in the README')
    for_you      = models.TextField(blank=True)
    sent_at      = models.DateTimeField(null=True, blank=True)
    added        = models.BooleanField(default=False, help_text='Added to the news digest')

    class Meta:
        ordering = ['-sent_at', '-weekly_gain']

    def __str__(self):
        return self.full_name

    @property
    def url(self):
        return f'https://github.com/{self.full_name}'


class RadarRun(models.Model):
    started_at = models.DateTimeField(auto_now_add=True)
    status     = models.CharField(max_length=10, default='running')
    picked     = models.JSONField(default=list, blank=True)   # RadarRepo ids, best first
    log        = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
