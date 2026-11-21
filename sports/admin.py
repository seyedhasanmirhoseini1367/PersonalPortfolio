from django.contrib import admin

from .models import EventRSVP, Follow, Notice, PostComment, PostSticker, SavedPost, SportPost, SportsProfile


@admin.register(SportPost)
class SportPostAdmin(admin.ModelAdmin):
    list_display = ('author', 'sport', 'kind', 'text', 'event_at', 'created_at')
    list_filter = ('sport', 'kind')
    search_fields = ('text', 'author__email')


for model in (PostSticker, PostComment, EventRSVP, Follow, SavedPost, Notice, SportsProfile):
    admin.site.register(model)
