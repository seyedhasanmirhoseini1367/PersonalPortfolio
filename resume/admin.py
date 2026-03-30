from django.contrib import admin
from .models import (
    ResumeSetting, Education, Experience, Skill,
    ProjectHighlight, Certification, Language
)

@admin.register(ResumeSetting)
class ResumeSettingAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'job_title', 'email', 'is_active']
    fieldsets = (
        ('Personal Information', {
            'fields': ('full_name', 'job_title', 'email', 'phone', 'location', 'website')
        }),
        ('Professional Summary', {
            'fields': ('professional_summary',)
        }),
        ('Social Links', {
            'fields': ('github_url', 'linkedin_url', 'kaggle_url')
        }),
        ('Settings', {
            'fields': ('is_active', 'last_updated')
        }),
    )
    readonly_fields = ['last_updated']

@admin.register(Education)
class EducationAdmin(admin.ModelAdmin):
    list_display = ['institution', 'degree', 'field_of_study', 'start_date', 'end_date', 'display_order']
    list_editable = ['display_order']
    list_filter = ['degree', 'institution']
    search_fields = ['institution', 'field_of_study']

@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ['company', 'position', 'employment_type', 'start_date', 'end_date', 'display_order']
    list_editable = ['display_order']
    list_filter = ['employment_type', 'company']
    search_fields = ['company', 'position']

@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'proficiency', 'is_featured', 'display_order']
    list_editable = ['proficiency', 'is_featured', 'display_order']
    list_filter = ['category', 'proficiency']
    search_fields = ['name']

@admin.register(ProjectHighlight)
class ProjectHighlightAdmin(admin.ModelAdmin):
    list_display = ['title', 'start_date', 'end_date', 'display_order']
    list_editable = ['display_order']
    search_fields = ['title']

@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ['name', 'issuing_organization', 'issue_date', 'display_order']
    list_editable = ['display_order']
    search_fields = ['name', 'issuing_organization']

@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['language', 'proficiency', 'display_order']
    list_editable = ['display_order']
    list_filter = ['proficiency']