# projects/admin.py
import os
import json
from django.contrib import admin
from django.utils.html import format_html
from django import forms
from .models import Projects, ProjectComment


class ProjectsAdminForm(forms.ModelForm):
    class Meta:
        model = Projects
        fields = '__all__'

    def clean_rag_document(self):
        """Validate uploaded RAG document"""
        rag_doc = self.cleaned_data.get('rag_document')
        if rag_doc:
            if rag_doc.size > 10 * 1024 * 1024:
                raise forms.ValidationError("File size must be under 10MB")

            import os
            ext = os.path.splitext(rag_doc.name)[1].lower()
            allowed_extensions = ['.pdf', '.docx', '.txt', '.md']
            if ext not in allowed_extensions:
                raise forms.ValidationError(
                    f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
                )

        return rag_doc


@admin.register(Projects)
class ProjectAdmin(admin.ModelAdmin):
    form = ProjectsAdminForm

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj:
            # Clear any FileField/ImageField references whose files no longer exist
            # so Django's widget doesn't crash calling os.path.getsize() on them.
            for field in obj._meta.get_fields():
                if hasattr(field, 'upload_to'):  # FileField / ImageField
                    file_field = getattr(obj, field.name)
                    if file_field and file_field.name:
                        try:
                            full_path = file_field.path
                            if not os.path.exists(full_path):
                                setattr(obj, field.name, None)
                        except (ValueError, NotImplementedError):
                            pass
        return obj

    # ── List view ─────────────────────────────────────────────────────────────

    list_display = [
        'title',
        'project_type',
        'difficulty_level',
        'prediction_input_type',
        'demo_ready_badge',
        'has_rag_document',
        'rag_document_processed',
        'is_featured',
        'is_public',
        'accuracy_score',
        'created_at',
    ]

    list_filter = [
        'project_type',
        'data_type',
        'difficulty_level',
        'prediction_input_type',
        'is_featured',
        'is_public',
        'prediction_endpoint',
        'model_type',
        'rag_document_processed',
        'created_at',
    ]

    search_fields = [
        'title',
        'short_description',
        'description',
        'target_feature',
    ]

    list_editable = [
        'is_featured',
        'is_public',
    ]

    # ── Detail view ───────────────────────────────────────────────────────────

    readonly_fields = [
        'created_at',
        'updated_at',
        'kaggle_percentile_display',
        'demo_ready_badge',
        'handler_status',
        'rag_document_uploaded_at',
        'rag_document_processed',
    ]

    fieldsets = (
        ('Basic information', {
            'fields': (
                'title',
                'short_description',
                'project_type',
                'difficulty_level',
                'data_type',
                'is_featured',
                'is_public',
            )
        }),

        ('Prediction demo', {
            'description': (
                'To enable the demo: (1) upload a trained model file, '
                '(2) choose input type, (3) fill in the config below, '
                '(4) tick "Prediction endpoint".'
            ),
            'fields': (
                'trained_model',
                'model_type',
                'target_feature',
                'prediction_input_type',
                'file_input_config',
                'input_features',
                'prediction_endpoint',
                'demo_ready_badge',
                'handler_status',
            ),
        }),

        ('Project details', {
            'fields': (
                'description',
                'business_problem',
                'technical_approach',
                'challenges',
                'key_achievements',
                'lessons_learned',
            )
        }),

        ('Technical specifications', {
            'fields': (
                'skills_used',
                'libraries_used',
                'evaluation_metric',
            )
        }),

        ('Performance metrics', {
            'fields': (
                'accuracy_score',
                'kaggle_rank',
                'total_competitors',
                'kaggle_percentile_display',
            )
        }),

        ('RAG Document for AI Interpretation', {
            'description': (
                'Upload a detailed document (thesis, research paper, technical spec) about this project. '
                'The AI will use this as context for better interpretations. '
                'Supported formats: PDF, DOCX, TXT, MD. Max size: 10MB'
            ),
            'fields': (
                'rag_document',
                'rag_document_uploaded_at',
                'rag_document_processed',
            ),
        }),

        ('Media & links', {
            'fields': (
                'featured_image',
                'additional_images',
                'github_url',
                'kaggle_url',
                'live_demo_url',
                'dataset_url',
            )
        }),

        ('Project management', {
            'fields': (
                'start_date',
                'end_date',
                'time_spent',
            )
        }),

        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    radio_fields = {
        'project_type': admin.HORIZONTAL,
        'data_type': admin.HORIZONTAL,
        'difficulty_level': admin.HORIZONTAL,
        'model_type': admin.HORIZONTAL,
        'prediction_input_type': admin.HORIZONTAL,
    }

    actions = [
        'make_featured', 'remove_featured',
        'make_public', 'make_private',
        'enable_prediction', 'disable_prediction',
        'process_rag_documents',
    ]

    ordering = ['-created_at']

    # ── Custom display methods ────────────────────────────────────────────────

    @admin.display(description='Demo ready')
    def demo_ready_badge(self, obj):
        """Green tick / red cross with tooltip explaining what's missing."""
        if obj.has_prediction_capability():
            return format_html(
                '<span style="color:#16a34a; font-weight:600;">✔ Ready</span>'
            )
        missing = []
        if not obj.trained_model:
            missing.append('model file')
        if not obj.prediction_endpoint:
            missing.append('"Prediction endpoint" checkbox')
        if not obj.is_public:
            missing.append('"Is public" checkbox')
        tips = ', '.join(missing) if missing else 'unknown'
        return format_html(
            '<span style="color:#dc2626;" title="Missing: {tips}">✘ Not ready</span>',
            tips=tips,
        )

    @admin.display(description='Has RAG Doc', boolean=True)
    def has_rag_document(self, obj):
        return bool(obj.rag_document)

    @admin.display(description='Kaggle percentile')
    def kaggle_percentile_display(self, obj):
        pct = obj.get_kaggle_percentile()
        return f'Top {pct}%' if pct else '—'

    @admin.display(description='Handler status')
    def handler_status(self, obj):
        """Shows whether the configured inference handler is registered."""
        if obj.prediction_input_type != 'file':
            return '— (manual mode, no handler needed)'

        cfg = obj.file_input_config or {}
        slug = cfg.get('handler', '').strip()

        if not slug:
            return format_html(
                '<span style="color:#b45309;">⚠ No "handler" key in file_input_config.</span>'
            )

        try:
            from projects.inference.registry import _REGISTRY
            if slug in _REGISTRY:
                return format_html(
                    '<span style="color:#16a34a;">✔ Handler <code>{}</code> is registered.</span>',
                    slug,
                )
            available = ', '.join(sorted(_REGISTRY.keys())) or 'none loaded'
            return format_html(
                '<span style="color:#dc2626;">✘ Handler <code>{slug}</code> not found. '
                'Available: {available}</span>',
                slug=slug,
                available=available,
            )
        except Exception as e:
            return format_html(
                '<span style="color:#dc2626;">Could not check registry: {}</span>', str(e)
            )

    # ── Form customisation ────────────────────────────────────────────────────

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        form.base_fields['skills_used'].help_text = (
                'Comma-separated skill keys. Valid values: '
                + ', '.join(c[0] for c in Projects.SKILL_CHOICES)
        )

        form.base_fields['input_features'].help_text = (
            'Used for manual mode only. JSON array of feature definitions. '
            'Example: [{"name": "age", "type": "number", "description": "Patient age in years"}]'
        )

        form.base_fields['file_input_config'].help_text = (
            'Used for file-upload mode. Must include a "handler" key matching a '
            'registered inference handler. '
            'Example for EEG seizure: '
            '{"handler": "seizure_eeg", "accepted_formats": ["parquet", "csv"], '
            '"description": "Upload EEG segment", '
            '"sampling_rate_hz": 256, '
            '"expected_channels": ["Fp1", "Fp2"], '
            '"label_map": {"0": "No seizure", "1": "Seizure detected"}}'
        )

        return form

    # ── Bulk actions ──────────────────────────────────────────────────────────

    @admin.action(description='Mark selected as featured')
    def make_featured(self, request, queryset):
        n = queryset.update(is_featured=True)
        self.message_user(request, f'{n} project(s) marked as featured.')

    @admin.action(description='Remove featured status')
    def remove_featured(self, request, queryset):
        n = queryset.update(is_featured=False)
        self.message_user(request, f'{n} project(s) removed from featured.')

    @admin.action(description='Make selected public')
    def make_public(self, request, queryset):
        n = queryset.update(is_public=True)
        self.message_user(request, f'{n} project(s) made public.')

    @admin.action(description='Make selected private')
    def make_private(self, request, queryset):
        n = queryset.update(is_public=False)
        self.message_user(request, f'{n} project(s) made private.')

    @admin.action(description='Enable prediction demo')
    def enable_prediction(self, request, queryset):
        n = queryset.update(prediction_endpoint=True)
        self.message_user(request, f'{n} project(s) demo enabled.')

    @admin.action(description='Disable prediction demo')
    def disable_prediction(self, request, queryset):
        n = queryset.update(prediction_endpoint=False)
        self.message_user(request, f'{n} project(s) demo disabled.')

    @admin.action(description='Process selected RAG documents')
    def process_rag_documents(self, request, queryset):
        processed = 0
        failed = 0
        for project in queryset:
            if project.rag_document and not project.rag_document_processed:
                if project.process_rag_document():
                    processed += 1
                else:
                    failed += 1
        self.message_user(
            request,
            f'Processed {processed} documents. Failed: {failed}'
        )


@admin.register(ProjectComment)
class ProjectCommentAdmin(admin.ModelAdmin):
    list_display = ('truncated_content', 'author', 'project', 'parent', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'created_at', 'project')
    search_fields = ('content', 'author__username', 'project__title')
    readonly_fields = ('created_at', 'updated_at')
    list_editable = ('is_approved',)
    actions = ['approve_comments', 'disapprove_comments']

    fieldsets = (
        ('Comment', {
            'fields': ('project', 'author', 'parent', 'content'),
        }),
        ('Moderation', {
            'fields': ('is_approved',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def truncated_content(self, obj):
        return obj.content[:60] + '…' if len(obj.content) > 60 else obj.content
    truncated_content.short_description = 'Comment'

    @admin.action(description='Approve selected comments')
    def approve_comments(self, request, queryset):
        n = queryset.update(is_approved=True)
        self.message_user(request, f'{n} comment(s) approved.')

    @admin.action(description='Disapprove selected comments')
    def disapprove_comments(self, request, queryset):
        n = queryset.update(is_approved=False)
        self.message_user(request, f'{n} comment(s) disapproved.')


# ── Site header ───────────────────────────────────────────────────────────────

admin.site.site_header = 'HasanPortfolio Administration'
admin.site.site_title = 'HasanPortfolio Admin'
admin.site.index_title = 'Data Science Portfolio Management'