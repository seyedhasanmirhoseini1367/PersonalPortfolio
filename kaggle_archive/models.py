from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Technique(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Competition(models.Model):
    TYPE_CHOICES = [
        ('tabular',     'Tabular'),
        ('cv',          'Computer Vision'),
        ('nlp',         'NLP'),
        ('timeseries',  'Time Series'),
        ('audio',       'Audio'),
        ('multimodal',  'Multimodal'),
        ('rl',          'Reinforcement Learning'),
        ('other',       'Other'),
    ]

    DOMAIN_CHOICES = [
        ('healthcare',  'Healthcare'),
        ('finance',     'Finance'),
        ('science',     'Science'),
        ('retail',      'Retail'),
        ('government',  'Government'),
        ('environment', 'Environment'),
        ('autonomous',  'Autonomous Vehicles'),
        ('nlp_domain',  'Language & Text'),
        ('other',       'Other'),
    ]

    name             = models.CharField(max_length=300)
    slug             = models.SlugField(max_length=320, unique=True, blank=True)
    competition_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    domain           = models.CharField(max_length=20, choices=DOMAIN_CHOICES, default='other')
    host             = models.CharField(max_length=150, blank=True)
    prize_pool       = models.CharField(max_length=50, blank=True, help_text='e.g. $100,000')
    num_teams        = models.PositiveIntegerField(default=0)
    description      = models.TextField(blank=True)
    kaggle_url       = models.URLField(blank=True)
    evaluation_metric = models.CharField(max_length=100, blank=True)
    end_date         = models.DateField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    # Comparison of the top writeups (kaggle_archive/summarizer.py)
    insights              = models.JSONField(null=True, blank=True)
    insights_generated_at = models.DateTimeField(null=True, blank=True)
    # Monthly Playground Series (kaggle_archive/playground.py); blank for Featured/Research.
    SERIES_PLAYGROUND = 'playground'
    series            = models.CharField(max_length=20, blank=True, db_index=True)
    season            = models.PositiveSmallIntegerField(null=True, blank=True)
    episode           = models.PositiveSmallIntegerField(null=True, blank=True)
    start_date        = models.DateField(null=True, blank=True)
    task              = models.CharField(max_length=20, blank=True, help_text='classification / regression / other')
    analyzed_at       = models.DateTimeField(null=True, blank=True, help_text='Winners and write-ups fetched')
    analysis_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-end_date', '-created_at']
        indexes  = [
            models.Index(fields=['competition_type']),
            models.Index(fields=['domain']),
            models.Index(fields=['-end_date']),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('kaggle_archive:competition_detail', args=[self.slug])

    def get_year(self):
        return self.end_date.year if self.end_date else None


class Solution(models.Model):
    MEDAL_CHOICES = [
        ('gold',   'Gold'),
        ('silver', 'Silver'),
        ('bronze', 'Bronze'),
        ('other',  'Other'),
    ]

    competition        = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name='solutions')
    rank               = models.PositiveIntegerField()
    team_name          = models.CharField(max_length=200)
    score              = models.CharField(max_length=50, blank=True, help_text='e.g. 0.9821')
    medal              = models.CharField(max_length=10, choices=MEDAL_CHOICES, blank=True)
    approach_summary   = models.TextField(blank=True)
    techniques         = models.ManyToManyField(Technique, blank=True, related_name='solutions')
    writeup_url        = models.URLField(blank=True)
    writeup_title      = models.CharField(max_length=300, blank=True)
    writeup_author     = models.CharField(max_length=200, blank=True)
    writeup_content    = models.TextField(blank=True, help_text='Full writeup body in markdown')
    writeup_fetched_at = models.DateTimeField(null=True, blank=True)
    # Structured learning card made from the writeup (kaggle_archive/summarizer.py)
    card               = models.JSONField(null=True, blank=True)
    card_generated_at  = models.DateTimeField(null=True, blank=True)
    is_public          = models.BooleanField(default=True)

    class Meta:
        ordering        = ['rank']
        unique_together = [['competition', 'rank']]

    def __str__(self):
        return f'#{self.rank} {self.team_name} — {self.competition.name}'

    def medal_icon(self):
        return {'gold': '1st', 'silver': '2nd', 'bronze': '3rd'}.get(self.medal, f'#{self.rank}')



class ExtractionJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done',    'Done'),
        ('failed',  'Failed'),
    ]

    url             = models.CharField(max_length=500)
    slug            = models.CharField(max_length=200, blank=True)
    top_n           = models.PositiveIntegerField(default=10)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    log             = models.TextField(blank=True)
    competition     = models.ForeignKey(
        Competition, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='extraction_jobs'
    )
    solutions_saved = models.PositiveIntegerField(default=0)
    created_at      = models.DateTimeField(auto_now_add=True)
    finished_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Job #{self.id} — {self.url[:60]} [{self.status}]'

    def duration(self):
        if self.finished_at and self.created_at:
            return int((self.finished_at - self.created_at).total_seconds())
        return None


class KaggleSyncRun(models.Model):
    """One monthly (or manual) update of the archive (kaggle_archive/auto.py)."""
    trigger     = models.CharField(max_length=10, default="auto")
    status      = models.CharField(max_length=10, default="running")
    log         = models.TextField(blank=True)
    processed   = models.PositiveIntegerField(default=0)
    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class KaggleSyncItem(models.Model):
    """What the auto-update decided about one Kaggle competition."""
    STATUS_ARCHIVED = "archived"
    STATUS_SKIPPED  = "skipped"
    STATUS_FAILED   = "failed"
    slug         = models.CharField(max_length=200, unique=True)
    title        = models.CharField(max_length=300, blank=True)
    category     = models.CharField(max_length=30, blank=True)
    deadline     = models.DateTimeField(null=True, blank=True)
    status       = models.CharField(max_length=10, blank=True)
    writeups     = models.PositiveIntegerField(default=0)
    attempts     = models.PositiveIntegerField(default=0)
    reason       = models.TextField(blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-deadline"]

    def __str__(self):
        return f"{self.slug} ({self.status})"


class LearnedLesson(models.Model):
    """A lesson a signed-in user marked as learned (Trends / competition pages)."""
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learned_lessons")
    competition = models.ForeignKey(Competition, on_delete=models.CASCADE, related_name="learned_by")
    lesson_key  = models.CharField(max_length=64, help_text="sha256 of the lesson text")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "competition", "lesson_key"]


class PlaygroundYear(models.Model):
    """"The year at a glance" for one Playground season, compared across its episodes."""
    season       = models.PositiveSmallIntegerField(unique=True)
    year         = models.PositiveSmallIntegerField()
    summary      = models.JSONField(default=dict, blank=True)
    based_on     = models.PositiveSmallIntegerField(default=0, help_text='Analysed episodes it was built from')
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-year']

    def __str__(self):
        return f'Playground {self.year} (season {self.season})'
