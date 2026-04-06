# stories/admin.py - CORRECTED VERSION
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib import messages
from .models import Story, Tag, Comment, StoryView, StoryLike


class TagInline(admin.TabularInline):
    model = Story.tags.through
    extra = 1
    verbose_name = 'Tag'
    verbose_name_plural = 'Tags'


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ('author', 'content', 'created_at')
    can_delete = True
    show_change_link = True


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):

    class Media:
        css = {
            'all': ('https://cdn.jsdelivr.net/npm/quill@2.0.2/dist/quill.snow.css',)
        }
        js = (
            'https://cdn.jsdelivr.net/npm/quill@2.0.2/dist/quill.js',
            'stories/admin_quill.js',
        )

    list_display = (
    'title', 'author', 'status', 'is_featured', 'view_count', 'likes_count_display', 'published_at', 'created_at')
    list_filter = ('status', 'is_featured', 'created_at', 'published_at', 'author')
    search_fields = ('title', 'content', 'excerpt', 'author__username')
    readonly_fields = ('slug', 'view_count', 'read_time_minutes', 'created_at', 'updated_at', 'likes_count_display')
    # Remove prepopulated_fields completely
    date_hierarchy = 'published_at'
    ordering = ('-published_at', '-created_at')
    actions = ['make_published', 'make_draft', 'toggle_featured']

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'author', 'excerpt', 'content')
        }),
        ('Media & Presentation', {
            'fields': ('featured_image', 'tags', 'status', 'is_featured')
        }),
        ('Engagement Settings', {
            'fields': ('allow_comments',)
        }),
        ('Statistics', {
            'fields': ('view_count', 'likes_count_display', 'read_time_minutes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'published_at'),
            'classes': ('collapse',)
        }),
    )

    inlines = [TagInline, CommentInline]

    def likes_count_display(self, obj):
        return obj.likes_count

    likes_count_display.short_description = 'Likes'

    def make_published(self, request, queryset):
        updated = queryset.update(status=Story.Status.PUBLISHED, published_at=timezone.now())
        self.message_user(request, f'{updated} story(s) published successfully.', messages.SUCCESS)

    make_published.short_description = "Mark selected stories as published"

    def make_draft(self, request, queryset):
        updated = queryset.update(status=Story.Status.DRAFT, published_at=None)
        self.message_user(request, f'{updated} story(s) marked as draft.', messages.SUCCESS)

    make_draft.short_description = "Mark selected stories as draft"

    def toggle_featured(self, request, queryset):
        for story in queryset:
            story.is_featured = not story.is_featured
            story.save()
        self.message_user(request, f'{queryset.count()} story(s) featured status toggled.', messages.SUCCESS)

    toggle_featured.short_description = "Toggle featured status"


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'story_count', 'created_at')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at',)

    def story_count(self, obj):
        return obj.stories.count()

    story_count.short_description = 'Number of Stories'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('truncated_content', 'author', 'story', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'created_at', 'story')
    search_fields = ('content', 'author__username', 'story__title')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['approve_comments', 'disapprove_comments']

    fieldsets = (
        ('Comment Content', {
            'fields': ('story', 'author', 'content', 'parent')
        }),
        ('Moderation', {
            'fields': ('is_approved',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def truncated_content(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content

    truncated_content.short_description = 'Content'

    def approve_comments(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f'{updated} comment(s) approved.', messages.SUCCESS)

    approve_comments.short_description = "Approve selected comments"

    def disapprove_comments(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, f'{updated} comment(s) disapproved.', messages.SUCCESS)

    disapprove_comments.short_description = "Disapprove selected comments"


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
    list_display = ('story', 'ip_address', 'viewed_at')
    list_filter = ('viewed_at', 'story')
    search_fields = ('ip_address', 'story__title')
    readonly_fields = ('story', 'ip_address', 'user_agent', 'viewed_at')
    date_hierarchy = 'viewed_at'

    def has_add_permission(self, request):
        return False  # Story views should only be created automatically


@admin.register(StoryLike)
class StoryLikeAdmin(admin.ModelAdmin):
    list_display = ('story', 'user', 'created_at')
    list_filter = ('created_at', 'story', 'user')
    search_fields = ('story__title', 'user__username')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False  # Likes should be created via the UI, not admin
