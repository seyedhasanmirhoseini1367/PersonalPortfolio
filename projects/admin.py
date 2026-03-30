from django.contrib import admin
from .models import Projects


@admin.register(Projects)
class ProjectAdmin(admin.ModelAdmin):
    """
    Admin configuration for Project model - Data Science Portfolio
    """
    # List display configuration
    list_display = [
        'title',
        'project_type',
        'difficulty_level',
        'is_featured',
        'is_public',
        'prediction_endpoint',
        'has_prediction_capability',
        'evaluation_metric',
        'accuracy_score',
        'created_at',
    ]

    list_filter = [
        'project_type',
        'data_type',
        'difficulty_level',
        'is_featured',
        'is_public',
        'prediction_endpoint',
        'model_type',
        'start_date',
        'created_at'
    ]

    search_fields = [
        'title',
        'short_description',
        'description',
        'business_problem',
        'technical_approach',
        'target_feature'
    ]

    list_editable = ['is_featured', 'is_public', 'prediction_endpoint', 'evaluation_metric', 'accuracy_score']

    readonly_fields = ['created_at', 'updated_at', 'get_kaggle_percentile_display', 'has_prediction_capability']

    # Add actions
    actions = ['make_featured', 'make_public', 'make_private', 'enable_prediction', 'disable_prediction']

    # Fieldsets for organized form display
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'title',
                'short_description',
                'project_type',
                'difficulty_level',
                'data_type',
                'is_featured',
                'is_public'
            )
        }),

        ('Machine Learning Model', {
            'fields': (
                'trained_model',
                'model_type',
                'prediction_endpoint',
                'has_prediction_capability',
                'target_feature',
                'input_features',
            )
        }),

        ('Project Details', {
            'fields': (
                'description',
                'business_problem',
                'technical_approach',
                'challenges',
                'key_achievements',
                'lessons_learned'
            )
        }),

        ('Technical Specifications', {
            'fields': (
                'skills_used',
                'libraries_used',
                'evaluation_metric',
            )
        }),

        ('Performance Metrics', {
            'fields': (
                'accuracy_score',
                'kaggle_rank',
                'total_competitors',
                'get_kaggle_percentile_display'
            )
        }),

        ('Media & Links', {
            'fields': (
                'featured_image',
                'additional_images',
                'github_url',
                'kaggle_url',
                'live_demo_url',
                'dataset_url'
            )
        }),

        ('Project Management', {
            'fields': (
                'start_date',
                'end_date',
                'time_spent'
            )
        }),

        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # Custom method to display Kaggle percentile
    def get_kaggle_percentile_display(self, obj):
        if obj.kaggle_rank and obj.total_competitors:
            percentile = obj.get_kaggle_percentile()
            return f"Top {percentile}%"
        return "N/A"

    get_kaggle_percentile_display.short_description = "Kaggle Percentile"

    # Custom method to display prediction capability
    def has_prediction_capability(self, obj):
        return obj.has_prediction_capability()

    has_prediction_capability.boolean = True
    has_prediction_capability.short_description = "Prediction Ready"

    # Custom actions
    def make_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} projects marked as featured.')

    make_featured.short_description = "Mark selected projects as featured"

    def make_public(self, request, queryset):
        updated = queryset.update(is_public=True)
        self.message_user(request, f'{updated} projects made public.')

    make_public.short_description = "Make selected projects public"

    def make_private(self, request, queryset):
        updated = queryset.update(is_public=False)
        self.message_user(request, f'{updated} projects made private.')

    make_private.short_description = "Make selected projects private"

    def enable_prediction(self, request, queryset):
        updated = queryset.update(prediction_endpoint=True)
        self.message_user(request, f'{updated} projects enabled for prediction.')

    enable_prediction.short_description = "Enable prediction for selected projects"

    def disable_prediction(self, request, queryset):
        updated = queryset.update(prediction_endpoint=False)
        self.message_user(request, f'{updated} projects disabled for prediction.')

    disable_prediction.short_description = "Disable prediction for selected projects"

    # Custom form configuration
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Add help texts dynamically
        form.base_fields['skills_used'].help_text = "Select from: " + ", ".join(
            [choice[0] for choice in Projects.SKILL_CHOICES])

        # Help text for input_features
        form.base_fields['input_features'].help_text = (
            "Enter as JSON array. Example: ["
            '{"name": "age", "type": "number", "description": "Person\'s age"}, '
            '{"name": "income", "type": "number", "description": "Annual income"}'
            "]"
        )

        return form

    # Configure the add/edit form
    filter_horizontal = []
    radio_fields = {
        'project_type': admin.HORIZONTAL,
        'data_type': admin.HORIZONTAL,
        'difficulty_level': admin.HORIZONTAL,
        'model_type': admin.HORIZONTAL
    }

    # Ordering in admin
    ordering = ['-created_at']


# Admin site customization
admin.site.site_header = "HasanPortfolio Administration"
admin.site.site_title = "HasanPortfolio Admin"
admin.site.index_title = "Data Science Portfolio Management"
