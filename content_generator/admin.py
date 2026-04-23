from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from .models import CompanyProfile, CompetitorProfile, ServiceProduct, GenerationJob, CMSConnection


class ServiceProductInline(admin.StackedInline):
    model = ServiceProduct
    extra = 1
    fields = ['name', 'item_type', 'description', 'display_order']


class CMSConnectionInline(admin.TabularInline):
    model  = CMSConnection
    extra  = 0
    fields = ['name', 'cms_type', 'api_url', 'api_token', 'is_active']


@admin.register(CompetitorProfile)
class CompetitorProfileAdmin(admin.ModelAdmin):
    list_display  = ['name', 'website', 'tracked_by_count', 'updated_at']
    search_fields = ['name', 'description']
    fieldsets = [
        (None,      {'fields': ['name', 'website']}),
        ('Content', {'fields': ['description']}),
        ('Notes',   {'fields': ['notes'], 'classes': ['collapse']}),
    ]

    def tracked_by_count(self, obj):
        return obj.tracked_by.count()
    tracked_by_count.short_description = 'Used by'


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display       = ['name', 'tone_of_voice', 'target_audience', 'service_count', 'rag_indexed', 'updated_at']
    search_fields      = ['name']
    inlines            = [ServiceProductInline, CMSConnectionInline]
    filter_horizontal  = ['competitors']
    fieldsets = [
        ('Company',     {'fields': ['name', 'tone_of_voice', 'target_audience']}),
        ('Content',     {'fields': ['about']}),
        ('Competitors', {'fields': ['competitors', 'competitor_info'], 'classes': ['collapse']}),
        ('RAG Status',  {'fields': ['rag_indexed'], 'classes': ['collapse']}),
    ]

    def service_count(self, obj):
        return obj.services.count()
    service_count.short_description = 'Services/Products'


@admin.register(ServiceProduct)
class ServiceProductAdmin(admin.ModelAdmin):
    list_display  = ['name', 'company', 'item_type', 'generate_button']
    list_filter   = ['item_type', 'company']
    search_fields = ['name', 'company__name']

    def generate_button(self, obj):
        url = (
            reverse('content_generator:form')
            + f'?profile={obj.company.pk}&service={obj.pk}'
        )
        return format_html(
            '<a href="{}" class="button" target="_blank" '
            'style="padding:3px 10px;background:#1e40af;color:white;'
            'border-radius:4px;font-size:12px;text-decoration:none;">'
            '✦ Generate Content</a>',
            url
        )
    generate_button.short_description = 'Generate'


@admin.register(CMSConnection)
class CMSConnectionAdmin(admin.ModelAdmin):
    list_display  = ['name', 'company_profile', 'cms_type', 'api_url', 'is_active', 'created_at']
    list_filter   = ['cms_type', 'is_active']
    search_fields = ['name', 'company_profile__name']


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display    = ['company_name', 'content_format', 'tone_preset', 'status',
                       'overall_score', 'user_approved_icon', 'variant_label', 'created_at']
    list_filter     = ['status', 'content_format', 'tone_preset', 'user_approved']
    search_fields   = ['company_name', 'goal']
    readonly_fields = ['id', 'job_group_id', 'variant_group_id', 'created_at', 'updated_at',
                       'content_en', 'content_fi', 'evaluation', 'overall_score', 'error_message',
                       'parent_job']

    def user_approved_icon(self, obj):
        if obj.user_approved is True:
            return '✅'
        if obj.user_approved is False:
            return '❌'
        return '—'
    user_approved_icon.short_description = 'Approved'

    def variant_label(self, obj):
        if obj.variant_index > 0:
            return f'v{obj.variant_index + 1}'
        return '—'
    variant_label.short_description = 'Variant'
