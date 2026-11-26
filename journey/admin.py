from django.contrib import admin

from .models import LearnerProfile, LessonPack, Membership, Progress, StudyGroup, StudyItem


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ['user']


@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'subject', 'invite_code', 'created_by', 'created_at']
    search_fields = ['name', 'invite_code']
    inlines = [MembershipInline]


class StudyItemInline(admin.TabularInline):
    model = StudyItem
    extra = 0
    fields = ['kind', 'order', 'front', 'form_in_text', 'grammar', 'meaning_en', 'confidence']


@admin.register(LessonPack)
class LessonPackAdmin(admin.ModelAdmin):
    list_display = ['title', 'group', 'status', 'created_by', 'image_count', 'created_at']
    list_filter = ['status', 'group']
    search_fields = ['title']
    inlines = [StudyItemInline]


@admin.register(Progress)
class ProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'item', 'reps', 'interval', 'lapses', 'due']
    list_filter = ['user']
    raw_id_fields = ['item']


@admin.register(LearnerProfile)
class LearnerProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'helper_language']
    list_filter = ['helper_language']
