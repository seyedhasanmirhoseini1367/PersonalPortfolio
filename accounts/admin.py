# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.contrib.admin import SimpleListFilter
from .models import CustomUser, UserProfile


class UserProfileInline(admin.StackedInline):
    """Inline admin for UserProfile"""
    model = UserProfile
    can_delete = False
    verbose_name_plural = _('Profile Details')
    fk_name = 'user'

    fieldsets = (
        (_('Professional Information'), {
            'fields': ('job_title', 'company', 'education', 'skills'),
            'classes': ('collapse', 'wide'),
        }),
        (_('Privacy Settings'), {
            'fields': ('show_email', 'show_phone'),
            'classes': ('collapse',),
        }),
        (_('Analytics'), {
            'fields': ('post_count', 'comment_count'),
            'classes': ('collapse',),
        }),
    )


class IsActiveFilter(SimpleListFilter):
    """Filter users by active status"""
    title = _('active status')
    parameter_name = 'is_active'

    def lookups(self, request, model_admin):
        return (
            ('active', _('Active')),
            ('inactive', _('Inactive')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(is_active=True)
        if self.value() == 'inactive':
            return queryset.filter(is_active=False)
        return queryset


class StaffStatusFilter(SimpleListFilter):
    """Filter users by staff status"""
    title = _('staff status')
    parameter_name = 'staff_status'

    def lookups(self, request, model_admin):
        return (
            ('staff', _('Staff')),
            ('non_staff', _('Non-Staff')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'staff':
            return queryset.filter(is_staff=True)
        if self.value() == 'non_staff':
            return queryset.filter(is_staff=False)
        return queryset


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Admin interface for CustomUser model"""

    # Inline profile
    inlines = (UserProfileInline,)

    # Fields for list display
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'is_active',
        'date_joined',
        'profile_picture_thumbnail',
        'action_buttons',
    )

    list_display_links = ('username', 'email')

    # Filters
    list_filter = (
        IsActiveFilter,
        StaffStatusFilter,
        'is_superuser',
        'date_joined',
        'last_login',
    )

    # Search fields
    search_fields = ('username', 'email', 'first_name', 'last_name')

    # Ordering
    ordering = ('-date_joined',)

    # Fieldsets for detail view
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal Info'), {
            'fields': (
                'first_name',
                'last_name',
                'email',
                'phone_number',
                'profile_picture',
                'profile_picture_preview',
            ),
            'classes': ('wide',),
        }),
        (_('Profile Information'), {
            'fields': ('bio', 'location', 'website'),
            'classes': ('wide',),
        }),
        (_('Social Links'), {
            'fields': ('twitter', 'linkedin', 'github'),
            'classes': ('collapse', 'wide'),
        }),
        (_('Permissions'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions',
            ),
            'classes': ('collapse',),
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined', 'last_updated'),
            'classes': ('collapse',),
        }),
        (_('Preferences'), {
            'fields': ('email_notifications',),
            'classes': ('collapse',),
        }),
    )

    # Readonly fields
    readonly_fields = ('date_joined', 'last_login', 'last_updated', 'profile_picture_preview')

    # Add form fields
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
        (_('Personal Info'), {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'phone_number'),
        }),
        (_('Permissions'), {
            'classes': ('wide',),
            'fields': ('is_active', 'is_staff', 'is_superuser'),
        }),
    )

    # Custom actions
    actions = ['activate_users', 'deactivate_users', 'make_staff', 'remove_staff']

    # Fields per page
    list_per_page = 25

    # Custom methods
    def profile_picture_thumbnail(self, obj):
        """Display profile picture thumbnail in list view"""
        if obj.profile_picture:
            return format_html(
                '<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />',
                obj.profile_picture.url
            )
        return format_html(
            '<div style="width: 50px; height: 50px; border-radius: 50%; background-color: #e9ecef; '
            'display: flex; align-items: center; justify-content: center; font-weight: bold; color: #6c757d;">'
            '{}</div>',
            obj.username[0].upper() if obj.username else '?'
        )

    profile_picture_thumbnail.short_description = _('Profile Picture')
    profile_picture_thumbnail.allow_tags = True

    def profile_picture_preview(self, obj):
        """Display profile picture preview in detail view"""
        if obj.profile_picture:
            return format_html(
                '<img src="{}" width="150" height="150" style="border-radius: 50%; object-fit: cover; '
                'border: 3px solid #dee2e6; margin: 10px 0;" />',
                obj.profile_picture.url
            )
        return format_html(
            '<div style="width: 150px; height: 150px; border-radius: 50%; background-color: #e9ecef; '
            'display: flex; align-items: center; justify-content: center; font-size: 48px; '
            'font-weight: bold; color: #6c757d; border: 3px solid #dee2e6; margin: 10px 0;">'
            '{}</div>',
            obj.username[0].upper() if obj.username else '?'
        )

    profile_picture_preview.short_description = _('Current Profile Picture')

    def action_buttons(self, obj):
        """Display action buttons in list view"""
        return format_html(
            '<div style="display: flex; gap: 5px;">'
            '<a href="{}" class="button" title="View Profile">👁️</a>'
            '<a href="{}" class="button" title="Edit">✏️</a>'
            '</div>',
            reverse('admin:accounts_customuser_change', args=[obj.id]),
            reverse('admin:accounts_customuser_change', args=[obj.id])
        )

    action_buttons.short_description = _('Actions')
    action_buttons.allow_tags = True

    # Custom admin actions
    def activate_users(self, request, queryset):
        """Activate selected users"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} users were successfully activated.')

    activate_users.short_description = _('Activate selected users')

    def deactivate_users(self, request, queryset):
        """Deactivate selected users"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} users were successfully deactivated.')

    deactivate_users.short_description = _('Deactivate selected users')

    def make_staff(self, request, queryset):
        """Make selected users staff members"""
        updated = queryset.update(is_staff=True)
        self.message_user(request, f'{updated} users were granted staff status.')

    make_staff.short_description = _('Make selected users staff')

    def remove_staff(self, request, queryset):
        """Remove staff status from selected users"""
        updated = queryset.update(is_staff=False)
        self.message_user(request, f'{updated} users had staff status removed.')

    remove_staff.short_description = _('Remove staff status from selected users')

    def get_inline_instances(self, request, obj=None):
        """Only show inline when editing an existing object"""
        if not obj:
            return []
        return super().get_inline_instances(request, obj)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin interface for UserProfile model (optional - usually accessed via User inline)"""

    list_display = ('user', 'job_title', 'company', 'post_count', 'comment_count')
    list_display_links = ('user',)

    list_filter = ('show_email', 'show_phone')

    search_fields = ('user__username', 'user__email', 'job_title', 'company')

    fieldsets = (
        (_('User Information'), {
            'fields': ('user', 'user_link'),
        }),
        (_('Professional Information'), {
            'fields': ('job_title', 'company', 'education'),
        }),
        (_('Skills'), {
            'fields': ('skills',),
            'classes': ('wide',),
        }),
        (_('Privacy Settings'), {
            'fields': ('show_email', 'show_phone'),
        }),
        (_('Analytics'), {
            'fields': ('post_count', 'comment_count'),
        }),
    )

    readonly_fields = ('user_link', 'post_count', 'comment_count')

    def user_link(self, obj):
        """Display link to user admin"""
        url = reverse('admin:accounts_customuser_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)

    user_link.short_description = _('User')

    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).select_related('user')


# Custom admin site configuration (optional)
class MyAdminSite(admin.AdminSite):
    site_header = _('PersonalPortfolio Administration')
    site_title = _('PersonalPortfolio Admin')
    index_title = _('Dashboard')

    def get_app_list(self, request):
        """
        Return a sorted list of all the installed apps that have been
        registered in this site.
        """
        app_list = super().get_app_list(request)

        # Custom sorting if needed
        return app_list

# Uncomment if you want to use custom admin site
# admin.site = MyAdminSite(name='myadmin')
# admin.site.register(CustomUser, CustomUserAdmin)
# admin.site.register(UserProfile, UserProfileAdmin)