from django.contrib import admin

from .models import PostComment, PostSticker, SportPost


@admin.register(SportPost)
class SportPostAdmin(admin.ModelAdmin):
    list_display = ('author', 'sport', 'text', 'created_at')
    list_filter = ('sport',)
    search_fields = ('text', 'author__email')


admin.site.register(PostSticker)
admin.site.register(PostComment)
