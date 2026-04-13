# resume/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    ResumeSetting, Education, Experience, Skill,
    ProjectHighlight, Certification, Language,
)


# ── Inlines ────────────────────────────────────────────────────────────────────

class EducationInline(admin.StackedInline):
    model = Education
    extra = 0
    min_num = 0
    fields = (
        ('institution', 'degree'),
        ('field_of_study', 'location'),
        ('start_date', 'end_date', 'is_current'),
        'gpa',
        'description',
        'display_order',
    )
    ordering = ('-end_date', '-start_date', 'display_order')


class ExperienceInline(admin.StackedInline):
    model = Experience
    extra = 0
    min_num = 0
    fields = (
        ('company', 'position'),
        ('employment_type', 'location'),
        ('start_date', 'end_date', 'is_current'),
        'description',
        'achievements',
        'display_order',
    )
    ordering = ('-end_date', '-start_date', 'display_order')


class SkillInline(admin.TabularInline):
    model = Skill
    extra = 0
    min_num = 0
    fields = ('name', 'category', 'proficiency', 'is_featured', 'display_order')
    ordering = ('category', 'display_order', 'name')


class CertificationInline(admin.TabularInline):
    model = Certification
    extra = 0
    min_num = 0
    fields = ('name', 'issuing_organization', 'issue_date', 'expiration_date',
              'credential_id', 'credential_url', 'display_order')
    ordering = ('-issue_date', 'display_order')


class LanguageInline(admin.TabularInline):
    model = Language
    extra = 0
    min_num = 0
    fields = ('language', 'proficiency', 'display_order')
    ordering = ('display_order',)


class ProjectHighlightInline(admin.StackedInline):
    model = ProjectHighlight
    extra = 0
    min_num = 0
    fields = (
        'title',
        ('start_date', 'end_date', 'is_current'),
        'description',
        'technologies_used',
        ('project_url', 'github_url'),
        'display_order',
    )
    ordering = ('-end_date', '-start_date', 'display_order')


# ── Main Resume admin (single page for everything) ─────────────────────────────

@admin.register(ResumeSetting)
class ResumeSettingAdmin(admin.ModelAdmin):
    inlines = [
        EducationInline,
        ExperienceInline,
        SkillInline,
        CertificationInline,
        LanguageInline,
        ProjectHighlightInline,
    ]

    fieldsets = (
        ('Personal Information', {
            'fields': (
                ('full_name', 'job_title'),
                ('email', 'phone'),
                ('location', 'website'),
            ),
        }),
        ('Professional Summary', {
            'fields': ('professional_summary',),
        }),
        ('Social Links', {
            'fields': (
                ('github_url', 'linkedin_url', 'kaggle_url'),
            ),
        }),
        ('CV Download', {
            'description': 'Upload your CV as a PDF to enable the "Download CV" button.',
            'fields': ('cv_pdf',),
            'classes': ('collapse',),
        }),
        ('Settings', {
            'fields': (('is_active', 'last_updated'),),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ('last_updated',)

    def has_add_permission(self, request):
        # Only allow one ResumeSetting instance
        return not ResumeSetting.objects.exists()

    def changelist_view(self, request, extra_context=None):
        """Redirect straight to the single resume edit page instead of list view."""
        from django.shortcuts import redirect
        from django.urls import reverse
        obj = ResumeSetting.objects.first()
        if obj:
            return redirect(
                reverse('admin:resume_resumesetting_change', args=[obj.pk])
            )
        return super().changelist_view(request, extra_context)

    @admin.display(description='Status')
    def status_badge(self, obj):
        return format_html(
            '<span style="color:#16a34a;">✔ Active</span>'
            if obj.is_active else
            '<span style="color:#dc2626;">✘ Inactive</span>'
        )
