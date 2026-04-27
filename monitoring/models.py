from django.db import models
from django.conf import settings


class PredictionLog(models.Model):
    """
    Logs every prediction made through the website or REST API.
    This is the core MLOps monitoring table — tracks drift, usage, latency.
    """
    project       = models.ForeignKey(
        'projects.Projects', on_delete=models.CASCADE,
        related_name='prediction_logs',
    )
    user          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='prediction_logs',
    )

    # Input/output
    input_data    = models.JSONField(default=dict, blank=True,
                                     help_text='Sanitised input sent to model')
    input_type    = models.CharField(max_length=20, default='manual')  # manual | file | api
    prediction    = models.FloatField(null=True, blank=True)
    confidence    = models.FloatField(null=True, blank=True)
    label         = models.CharField(max_length=100, blank=True)

    # Performance
    inference_ms  = models.IntegerField(null=True, blank=True,
                                         help_text='Inference latency in milliseconds')
    success       = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)

    # Context
    source        = models.CharField(max_length=20, default='web',
                                      help_text='web | api | demo')
    ip_address    = models.GenericIPAddressField(null=True, blank=True)
    user_agent    = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['project', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.project.title} | {self.label} | {self.created_at:%Y-%m-%d %H:%M}'


class MonitorRun(models.Model):
    """
    One row per synthetic-monitor execution.
    Groups all PredictionLogs from a single scheduler/manual run into an
    aggregate so you can track accuracy and latency trends over time.
    """
    TRIGGER_SCHEDULER = 'scheduler'
    TRIGGER_MANUAL    = 'manual'
    TRIGGER_CHOICES   = [
        (TRIGGER_SCHEDULER, 'Scheduler'),
        (TRIGGER_MANUAL,    'Manual'),
    ]

    project        = models.ForeignKey(
        'projects.Projects', on_delete=models.CASCADE,
        related_name='monitor_runs',
    )
    started_at     = models.DateTimeField()
    completed_at   = models.DateTimeField(null=True, blank=True)
    triggered_by   = models.CharField(
        max_length=20, default=TRIGGER_SCHEDULER, choices=TRIGGER_CHOICES,
    )

    # Sample counts
    n_samples      = models.IntegerField(default=0)
    n_success      = models.IntegerField(default=0)
    n_failed       = models.IntegerField(default=0)

    # Accuracy (only for samples with known labels)
    n_comparable   = models.IntegerField(default=0)
    n_correct      = models.IntegerField(default=0)

    # Performance aggregates
    avg_latency_ms = models.FloatField(null=True, blank=True)
    avg_confidence = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes  = [models.Index(fields=['project', 'started_at'])]

    def __str__(self):
        return f'{self.project.title} run @ {self.started_at:%Y-%m-%d %H:%M} ({self.n_samples} samples)'

    @property
    def accuracy(self):
        if self.n_comparable > 0:
            return round(self.n_correct / self.n_comparable * 100, 1)
        return None

    @property
    def duration_s(self):
        if self.completed_at and self.started_at:
            return round((self.completed_at - self.started_at).total_seconds(), 1)
        return None


class ModelHealthSnapshot(models.Model):
    """
    Daily snapshot of model health metrics.
    In production you'd compute these from PredictionLog aggregates.
    """
    project         = models.ForeignKey(
        'projects.Projects', on_delete=models.CASCADE,
        related_name='health_snapshots',
    )
    date            = models.DateField()
    total_requests  = models.IntegerField(default=0)
    success_rate    = models.FloatField(default=1.0, help_text='0.0–1.0')
    avg_latency_ms  = models.FloatField(null=True, blank=True)
    avg_confidence  = models.FloatField(null=True, blank=True)
    # Simple drift signal: stdev of confidence scores that day
    confidence_std  = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('project', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.project.title} health @ {self.date}'
