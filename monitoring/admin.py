from django.contrib import admin
from .models import PredictionLog, ModelHealthSnapshot, MonitorRun


@admin.register(PredictionLog)
class PredictionLogAdmin(admin.ModelAdmin):
    list_display  = ('project', 'label', 'confidence', 'inference_ms', 'success', 'source', 'created_at')
    list_filter   = ('project', 'success', 'source')
    search_fields = ('label', 'error_message')
    readonly_fields = ('created_at',)
    date_hierarchy  = 'created_at'


@admin.register(ModelHealthSnapshot)
class ModelHealthSnapshotAdmin(admin.ModelAdmin):
    list_display = ('project', 'date', 'total_requests', 'success_rate', 'avg_latency_ms')
    list_filter  = ('project',)
    date_hierarchy = 'date'


@admin.register(MonitorRun)
class MonitorRunAdmin(admin.ModelAdmin):
    list_display  = ('project', 'started_at', 'n_samples', 'n_success', 'n_failed',
                     'n_comparable', 'n_correct', 'avg_latency_ms', 'triggered_by')
    list_filter   = ('project', 'triggered_by')
    readonly_fields = ('started_at', 'completed_at')
    date_hierarchy  = 'started_at'
