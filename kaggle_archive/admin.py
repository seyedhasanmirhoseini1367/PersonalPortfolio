from django.contrib import admin
from .models import Competition, Solution, Technique


class SolutionInline(admin.TabularInline):
    model               = Solution
    extra               = 3
    filter_horizontal   = ['techniques']
    fields              = ['rank', 'team_name', 'medal', 'score', 'approach_summary',
                           'notebook_url', 'discussion_url', 'techniques', 'is_public']


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    list_display        = ['name', 'competition_type', 'domain', 'end_date', 'num_teams', 'prize_pool']
    list_filter         = ['competition_type', 'domain', 'end_date']
    search_fields       = ['name', 'host']
    prepopulated_fields = {'slug': ('name',)}
    inlines             = [SolutionInline]
    fieldsets = [
        ('Competition Info', {
            'fields': ('name', 'slug', 'competition_type', 'domain', 'host', 'kaggle_url')
        }),
        ('Details', {
            'fields': ('description', 'evaluation_metric', 'num_teams', 'prize_pool', 'end_date')
        }),
    ]


@admin.register(Solution)
class SolutionAdmin(admin.ModelAdmin):
    list_display        = ['rank', 'team_name', 'competition', 'medal', 'score']
    list_filter         = ['medal', 'competition__competition_type', 'is_public']
    search_fields       = ['team_name', 'competition__name']
    filter_horizontal   = ['techniques']


@admin.register(Technique)
class TechniqueAdmin(admin.ModelAdmin):
    list_display        = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    search_fields       = ['name']
