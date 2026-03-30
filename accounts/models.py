from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator


class CustomUser(AbstractUser):
    """
    Custom User model extending Django's AbstractUser
    """
    email = models.EmailField(_('email address'), unique=True)
    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
    )
    phone_number = models.CharField(validators=[phone_regex], max_length=17, blank=True)

    # Profile fields
    bio = models.TextField(_('biography'), blank=True, max_length=500)
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        blank=True,
        null=True,
        default='profile_pics/default.png'
    )
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)

    # Social links
    twitter = models.URLField(blank=True)
    linkedin = models.URLField(blank=True)
    github = models.URLField(blank=True)

    # Preferences
    email_notifications = models.BooleanField(default=True)

    # Timestamps
    date_joined = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    # Fix: Add custom related_name for groups and permissions
    groups = models.ManyToManyField(
        Group,
        verbose_name=_('groups'),
        blank=True,
        help_text=_(
            'The groups this user belongs to. A user will get all permissions '
            'granted to each of their groups.'
        ),
        related_name="customuser_set",  # Changed from default
        related_query_name="customuser",
    )
    user_permissions = models.ManyToManyField(
        Permission,
        verbose_name=_('user permissions'),
        blank=True,
        help_text=_('Specific permissions for this user.'),
        related_name="customuser_set",  # Changed from default
        related_query_name="customuser",
    )

    class Meta:
        ordering = ['-date_joined']
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        return self.username

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = f'{self.first_name} {self.last_name}'
        return full_name.strip()

    def get_short_name(self):
        """
        Return the short name for the user.
        """
        return self.first_name


class UserProfile(models.Model):
    """
    Extended user profile information
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    job_title = models.CharField(max_length=100, blank=True)
    company = models.CharField(max_length=100, blank=True)
    education = models.TextField(blank=True)
    skills = models.TextField(blank=True, help_text="Comma-separated list of skills")

    # Privacy settings
    show_email = models.BooleanField(default=False)
    show_phone = models.BooleanField(default=False)

    # Analytics
    post_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _('User Profile')
        verbose_name_plural = _('User Profiles')

    def __str__(self):
        return f"{self.user.username}'s Profile"

    def increment_post_count(self):
        self.post_count += 1
        self.save()

    def increment_comment_count(self):
        self.comment_count += 1
        self.save()


# Signals to create/update user profile automatically
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=CustomUser)
def save_user_profile(sender, instance, **kwargs):
    try:
        instance.profile.save()
    except UserProfile.DoesNotExist:
        UserProfile.objects.create(user=instance)
