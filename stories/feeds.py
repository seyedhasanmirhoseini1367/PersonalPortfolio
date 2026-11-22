"""RSS feed of the AI & ML news: daily digests and weekly roundups."""
from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils import timezone

from .models import Story, digest_q


class DigestFeed(Feed):
    title = 'HasanAI — AI & ML News Digest'
    description = ('Daily summaries of the notable AI and machine-learning papers and news, '
                   'each linked to its source, plus a weekly top-5 roundup.')

    def link(self):
        return reverse('stories:story_list')

    def items(self):
        return (Story.objects.filter(status=Story.Status.PUBLISHED, published_at__lte=timezone.now())
                .filter(digest_q()).order_by('-published_at')[:30])

    def item_title(self, story):
        return story.title

    def item_description(self, story):
        return story.content   # the full digest; every item already links to its source

    def item_link(self, story):
        return reverse('stories:story_detail', args=[story.slug])

    def item_pubdate(self, story):
        return story.published_at

    def item_categories(self, story):
        return [t.name for t in story.tags.all()]
