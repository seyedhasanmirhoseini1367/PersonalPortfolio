# stories/models.py - COMPLETE FIXED VERSION
from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils.text import slugify
from django.core.validators import MinLengthValidator, MaxLengthValidator
from django.utils import timezone


class Story(models.Model):
    """
    A story/blog post written by a user.
    """

    class Status(models.TextChoices):
        DRAFT = 'DF', 'Draft'
        PUBLISHED = 'PB', 'Published'
        ARCHIVED = 'AR', 'Archived'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stories',
        verbose_name='Author',
        help_text='The user who wrote this story'
    )

    title = models.CharField(
        max_length=200,
        verbose_name='Story Title',
        help_text='Enter a descriptive title (max 200 characters)',
        validators=[
            MinLengthValidator(10, message='Title must be at least 10 characters long.'),
            MaxLengthValidator(200, message='Title cannot exceed 200 characters.')
        ]
    )

    slug = models.SlugField(
        max_length=250,
        unique_for_date='published_at',
        blank=True,
        verbose_name='URL Slug',
        help_text='Auto-generated URL-friendly version of the title'
    )

    excerpt = models.TextField(
        max_length=500,
        blank=True,
        verbose_name='Short Excerpt',
        help_text='Brief summary of the story (max 500 characters)'
    )

    content = models.TextField(
        verbose_name='Story Content',
        help_text='Write your story here'
    )

    tags = models.ManyToManyField(
        'Tag',
        blank=True,
        related_name='stories',
        verbose_name='Story Tags',
        help_text='Categorize your story with relevant tags'
    )

    status = models.CharField(
        max_length=2,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name='Publication Status',
        help_text='Current status of the story'
    )

    featured_image = models.ImageField(
        upload_to='stories/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Featured Image',
        help_text='Optional image to accompany the story'
    )

    read_time_minutes = models.PositiveIntegerField(
        default=0,
        verbose_name='Estimated Read Time (minutes)',
        help_text='Auto-calculated reading time'
    )

    view_count = models.PositiveIntegerField(
        default=0,
        verbose_name='View Count',
        help_text='Number of times this story has been viewed'
    )

    is_featured = models.BooleanField(
        default=False,
        verbose_name='Featured Story',
        help_text='Mark this story as featured to highlight it'
    )

    allow_comments = models.BooleanField(
        default=True,
        verbose_name='Allow Comments',
        help_text='Enable or disable comments for this story'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created At'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Last Updated'
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Published At',
        help_text='Date and time when the story was published'
    )

    class Meta:
        verbose_name = 'Story'
        verbose_name_plural = 'Stories'
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['status']),
            models.Index(fields=['author']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(status__in=['DF', 'PB', 'AR']),
                name='valid_story_status'
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author.username}"

    def save(self, *args, **kwargs):
        # Auto-generate slug if not provided
        if not self.slug:
            self.slug = slugify(self.title)

        # Set published_at when status changes to PUBLISHED
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()

        # Auto-calculate read time
        word_count = len(self.content.split())
        self.read_time_minutes = max(1, round(word_count / 200))

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        if self.published_at:
            return reverse('stories:story_detail', args=[
                self.published_at.year,
                self.published_at.month,
                self.published_at.day,
                self.slug
            ])
        return reverse('stories:story_preview', args=[self.pk])

    def is_published(self):
        """Check if the story is published and available."""
        return self.status == self.Status.PUBLISHED and self.published_at is not None

    def increment_view_count(self):
        """Increment the view count atomically to prevent race conditions."""
        from django.db.models import F
        Story.objects.filter(id=self.id).update(view_count=F('view_count') + 1)
        self.refresh_from_db(fields=['view_count'])

    @property
    def likes_count(self):
        """Get the number of likes for this story."""
        return self.story_likes.count()

    def user_has_liked(self, user):
        """Check if a specific user has liked this story."""
        if user.is_authenticated:
            return self.story_likes.filter(user=user).exists()
        return False

    def like_story(self, user):
        """Add a like from a specific user."""
        if user.is_authenticated and not self.user_has_liked(user):
            StoryLike.objects.create(story=self, user=user)
            return True
        return False

    def unlike_story(self, user):
        """Remove a like from a specific user."""
        if user.is_authenticated:
            StoryLike.objects.filter(story=self, user=user).delete()
            return True
        return False

    def get_excerpt(self):
        """Get excerpt or generate one from content."""
        if self.excerpt:
            return self.excerpt
        return self.content[:200] + '...' if len(self.content) > 200 else self.content


class Tag(models.Model):
    """
    Tag for categorizing stories.
    """
    name = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='Tag Name',
        help_text='Name of the tag (max 50 characters)'
    )

    slug = models.SlugField(
        max_length=60,
        unique=True,
        verbose_name='URL Slug'
    )

    description = models.TextField(
        max_length=300,
        blank=True,
        verbose_name='Tag Description',
        help_text='Brief description of the tag'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tag'
        verbose_name_plural = 'Tags'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('stories:tag_detail', args=[self.slug])


class Comment(models.Model):
    """
    Comment on a story.
    """
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='comments',
        verbose_name='Story'
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='story_comments',
        verbose_name='Comment Author'
    )

    content = models.TextField(
        verbose_name='Comment Content',
        help_text='Write your comment here',
        validators=[MinLengthValidator(10, message='Comment must be at least 10 characters.')]
    )

    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='replies',
        verbose_name='Parent Comment'
    )

    is_approved = models.BooleanField(
        default=True,
        verbose_name='Approved',
        help_text='Approve or reject this comment'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Comment'
        verbose_name_plural = 'Comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['story', 'created_at']),
            models.Index(fields=['is_approved']),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on {self.story.title[:50]}"

    def is_reply(self):
        """Check if this comment is a reply to another comment."""
        return self.parent is not None


class StoryView(models.Model):
    """
    Track story views with additional information.
    """
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='story_views'
    )

    # ADDED: User field for authenticated users
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='story_views',
        verbose_name='User'
    )

    ip_address = models.GenericIPAddressField(
        verbose_name='IP Address'
    )

    user_agent = models.TextField(
        blank=True,
        verbose_name='User Agent'
    )

    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Story View'
        verbose_name_plural = 'Story Views'
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['story', 'viewed_at']),
            models.Index(fields=['story', 'user']),  # Added index for user
            models.Index(fields=['story', 'ip_address', 'viewed_at']),  # Added index for IP tracking
        ]

    def __str__(self):
        if self.user:
            return f"View by {self.user.username} on {self.story.title}"
        return f"View from {self.ip_address} on {self.story.title}"


class StoryLike(models.Model):
    """Track which users have liked which stories."""
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='story_likes'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_likes'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['story', 'user']  # Prevents duplicate likes
        verbose_name = 'Story Like'
        verbose_name_plural = 'Story Likes'
        indexes = [
            models.Index(fields=['story', 'user']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} likes {self.story.title}"
