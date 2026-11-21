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
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sport_posts')
    sport = models.CharField(max_length=20, choices=SPORT_CHOICES)
    text = models.CharField(max_length=280)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

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
        ordering = ['created_at']
