from django.contrib import admin
from .models import Walkthrough, WalkthroughBlock, WalkthroughReference


class WalkthroughBlockInline(admin.StackedInline):
    model  = WalkthroughBlock
    extra  = 1
    fields = ['order', 'block_type', 'content', 'image', 'caption']


class WalkthroughReferenceInline(admin.TabularInline):
    model  = WalkthroughReference
    extra  = 1
    fields = ['order', 'title', 'authors', 'url']


@admin.register(Walkthrough)
class WalkthroughAdmin(admin.ModelAdmin):
    list_display        = ['title', 'category', 'difficulty', 'is_published', 'order']
    list_filter          = ['category', 'difficulty', 'is_published']
    search_fields        = ['title', 'tagline', 'summary']
    prepopulated_fields  = {'slug': ('title',)}
    inlines              = [WalkthroughReferenceInline, WalkthroughBlockInline]
    fieldsets = [
        ('Walkthrough Info', {
            'fields': ('title', 'slug', 'tagline', 'icon', 'category', 'difficulty')
        }),
        ('Cover Image', {
            'fields': ('cover_image', 'cover_image_caption', 'cover_image_credit', 'cover_image_credit_url')
        }),
        ('Listing', {
            'fields': ('summary', 'is_published', 'order')
        }),
    ]


@admin.register(WalkthroughBlock)
class WalkthroughBlockAdmin(admin.ModelAdmin):
    list_display  = ['walkthrough', 'order', 'block_type', 'caption']
    list_filter   = ['block_type', 'walkthrough']
