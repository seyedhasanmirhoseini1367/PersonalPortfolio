from django.contrib import admin
from .models import Walkthrough, WalkthroughBlock, WalkthroughReference


class WalkthroughBlockInline(admin.StackedInline):
    """Read-only view of a walkthrough's content.

    Blocks are generated from the notebook, and every populate_walkthroughs run
    deletes and rebuilds all of them (and, since the image-orphan fix, deletes
    their image files too). So anything edited or added here is destroyed on the
    next deploy -- the form is shown for inspection, not for editing.

    Making it read-only also removes ~1,100 inputs from the change form on the
    longest walkthrough, which is what pushed it past DATA_UPLOAD_MAX_NUMBER_FIELDS.
    """
    model  = WalkthroughBlock
    extra  = 0
    fields = ['order', 'block_type', 'content', 'image', 'caption']
    readonly_fields = fields
    classes = ['collapse']
    can_delete = False
    verbose_name_plural = (
        'Content blocks (read-only - regenerated from the notebook on every deploy)'
    )

    def has_add_permission(self, request, obj=None):
        return False


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
    """Read-only, and registered only for cross-walkthrough inspection.

    Blocks are machine-generated: populate_walkthroughs wipes and rebuilds all
    of them on every deploy. Editing one here is overwritten and adding one is
    deleted outright, so the add/change/delete affordances would only ever cost
    someone their work. What the flat list IS good for is questions the
    per-walkthrough inline cannot answer -- searching content across all
    walkthroughs at once, or filtering every image block in the section.
    """
    list_display    = ['walkthrough', 'order', 'block_type', 'caption']
    list_filter     = ['block_type', 'walkthrough']
    search_fields   = ['content', 'caption']
    list_select_related = ['walkthrough']
    readonly_fields = ['walkthrough', 'order', 'block_type', 'content',
                       'image', 'caption']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
