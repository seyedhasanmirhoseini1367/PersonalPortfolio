from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Story


class StorySitemap(Sitemap):
    changefreq = 'weekly'
    priority   = 0.6

    def items(self):
        return Story.objects.filter(status='published')

    def location(self, obj):
        return reverse('stories:story_detail', args=[obj.slug])

    def lastmod(self, obj):
        return obj.updated_at
