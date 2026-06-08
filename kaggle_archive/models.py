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
