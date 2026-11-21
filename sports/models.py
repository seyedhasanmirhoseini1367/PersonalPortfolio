from django.conf import settings
from django.db import models

# Stickers each sport offers. Keys match the sticker definitions (G) in the
# page's script; the first one is what a double-tap picks.
SPORT_STICKERS = {
    'Football': ['net', 'fire', 'glove', 'card', 'crown'],
    'Drill': ['respect', 'note', 'fire'],
    'Padel': ['racket', 'fire', 'crown'],
    'Running': ['watch', 'fire', 'crown'],
}
SPORT_CHOICES = [(s, s) for s in SPORT_STICKERS]


class SportPost(models.Model):
    KIND_POST = 'post'
    KIND_EVENT = 'event'
    KIND_CHOICES = [(KIND_POST, 'Post'), (KIND_EVENT, 'Event')]

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_posts')
    sport = models.CharField(max_length=20, choices=SPORT_CHOICES)
    text = models.CharField(max_length=280)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_POST)
    # Only used when kind == 'event'
    event_at = models.DateTimeField(null=True, blank=True)
    place = models.CharField(max_length=80, blank=True)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.author} · {self.sport}: {self.text[:40]}'


class PostSticker(models.Model):
    """One sticker per user per post; picking another replaces it."""
    post = models.ForeignKey(SportPost, on_delete=models.CASCADE, related_name='stickers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_stickers')
    sticker = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['post', 'user'], name='one_sticker_per_user_per_post')]


class PostComment(models.Model):
    post = models.ForeignKey(SportPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_comments')
    text = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class EventRSVP(models.Model):
    """'I'm in' on an event post. Anyone beyond the capacity is on the waitlist, in join order."""
    post = models.ForeignKey(SportPost, on_delete=models.CASCADE, related_name='rsvps')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_rsvps')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['post', 'user'], name='one_rsvp_per_user_per_event')]


class Follow(models.Model):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_following')
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['follower', 'following'], name='follow_once')]


class SavedPost(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_saved')
    post = models.ForeignKey(SportPost, on_delete=models.CASCADE, related_name='saves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'post'], name='save_once')]


class Notice(models.Model):
    """A stored notification for things that can't be rebuilt from current data
    (someone left, you got a spot, a game changed or was cancelled)."""
    JOINED = 'joined'
    WAITLISTED = 'waitlisted'
    LEFT = 'left'
    PROMOTED = 'promoted'
    CHANGED = 'changed'
    CANCELLED = 'cancelled'
    TYPES = [(t, t) for t in (JOINED, WAITLISTED, LEFT, PROMOTED, CHANGED, CANCELLED)]

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_notices')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                              related_name='+')
    type = models.CharField(max_length=12, choices=TYPES)
    post = models.ForeignKey(SportPost, on_delete=models.CASCADE, null=True, blank=True, related_name='notices')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['recipient', '-created_at'])]


class SportsProfile(models.Model):
    """Per-user app state that doesn't belong on the site-wide user model."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sports_profile')
    notifications_seen_at = models.DateTimeField(null=True, blank=True)
