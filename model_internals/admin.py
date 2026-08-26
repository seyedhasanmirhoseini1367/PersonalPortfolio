from django.contrib import admin
from .models import Walkthrough, WalkthroughBlock, WalkthroughReference


class WalkthroughBlockInline(admin.StackedInline):
    model  = WalkthroughBlock
    # extra=0: the long walkthroughs already run to 136 blocks, and every form
    # rendered here is ~9 more POST fields on save (see
    # DATA_UPLOAD_MAX_NUMBER_FIELDS in settings). Add blocks deliberately.
    extra  = 0
    fields = ['order', 'block_type', 'content', 'image', 'caption']
    classes = ['collapse']
    verbose_name_plural = (
        'Content blocks - WARNING: rebuilt from the notebook, edits here are temporary'
    )


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
            'fields': ('title', 'slug', 'tagline', 'icon', 'category', 'difficulty'),
            'description': (
                'Overwritten on deploy. title, tagline, icon, category and difficulty '
                'are re-applied from populate_walkthroughs.py every time it runs, so '
                'edits made here are lost at the next deploy - change them in that '
                'file instead. slug is safe.'
            ),
        }),
        ('Cover Image', {
            'fields': ('cover_image', 'cover_image_caption', 'cover_image_credit',
                       'cover_image_credit_url'),
            'description': (
                'Safe to edit here. Cover images do not come from the notebooks and '
                'nothing overwrites them - this admin page is the only way to set one.'
            ),
        }),
        ('Listing', {
            'fields': ('summary', 'is_published', 'order'),
            'description': (
                'summary and order are overwritten on deploy (edit them in '
                'populate_walkthroughs.py). is_published is safe to change here.'
            ),
        }),
    ]


@admin.register(WalkthroughBlock)
class WalkthroughBlockAdmin(admin.ModelAdmin):
    list_display  = ['walkthrough', 'order', 'block_type', 'caption']
    list_filter   = ['block_type', 'walkthrough']
