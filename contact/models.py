from django.db import models
from django.core.validators import EmailValidator


class ContactProfile(models.Model):
    """
    Main contact profile - stores your contact information
    """
    PLATFORM_CHOICES = [
        ('GITHUB', 'GitHub'),
        ('LINKEDIN', 'LinkedIn'),
        ('KAGGLE', 'Kaggle'),
        ('EMAIL', 'Email'),
        ('TWITTER', 'Twitter'),
        ('PORTFOLIO', 'Portfolio'),
        ('OTHER', 'Other'),
    ]

    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    url = models.URLField(max_length=500)
    username = models.CharField(max_length=100, blank=True)
    display_name = models.CharField(max_length=100, help_text="How it appears on website")
    icon_class = models.CharField(max_length=50, default='fas fa-link', help_text="FontAwesome icon class")
    description = models.TextField(blank=True, help_text="Short description for this contact method")
    display_order = models.IntegerField(default=0, help_text="Order in which contacts appear")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'platform']
        verbose_name = "Contact Profile"
        verbose_name_plural = "Contact Profiles"

    def __str__(self):
        return f"{self.get_platform_display()} - {self.username}"


class ContactMessage(models.Model):
    """
    Stores messages received from website visitors
    """
    STATUS_CHOICES = [
        ('NEW', 'New'),
        ('READ', 'Read'),
        ('REPLIED', 'Replied'),
        ('SPAM', 'Spam'),
    ]

    name = models.CharField(max_length=100)
    email = models.EmailField(validators=[EmailValidator()])
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='NEW')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Contact Message"
        verbose_name_plural = "Contact Messages"

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"


class ContactSetting(models.Model):
    """
    Global contact settings
    """
    site_email = models.EmailField(default="seyedhasan.mirhoseini1367@gmail.com")
    contact_email = models.EmailField(help_text="Where contact form messages are sent")
    response_time = models.CharField(max_length=50, default="24-48 hours")
    availability_status = models.BooleanField(default=True)
    availability_message = models.TextField(default="I'm currently available for new opportunities and collaborations.")

    class Meta:
        verbose_name = "Contact Setting"
        verbose_name_plural = "Contact Settings"

    def __str__(self):
        return "Contact Settings"

    def save(self, *args, **kwargs):
        # Ensure only one settings instance exists
        self.__class__.objects.exclude(id=self.id).delete()
        super().save(*args, **kwargs)