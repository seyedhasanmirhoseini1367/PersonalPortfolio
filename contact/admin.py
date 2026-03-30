from django.contrib import admin
from .models import ContactProfile, ContactMessage, ContactSetting

@admin.register(ContactProfile)
class ContactProfileAdmin(admin.ModelAdmin):
    list_display = ['platform', 'username', 'display_order', 'is_active']
    list_editable = ['display_order', 'is_active']
    list_filter = ['platform', 'is_active']
    search_fields = ['username', 'display_name']

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'subject', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'email', 'subject', 'message']
    readonly_fields = ['created_at', 'updated_at', 'ip_address', 'user_agent']

@admin.register(ContactSetting)
class ContactSettingAdmin(admin.ModelAdmin):
    list_display = ['site_email', 'contact_email', 'availability_status']