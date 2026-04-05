from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Projects


class StaticViewSitemap(Sitemap):
    priority   = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['home', 'projects_list']

    def location(self, item):
        return reverse(item)


class ProjectSitemap(Sitemap):
    changefreq = 'monthly'
    priority   = 0.7

    def items(self):
        return Projects.objects.filter(is_public=True)

    def location(self, obj):
        return reverse('project_detail', args=[obj.pk])

    def lastmod(self, obj):
        return obj.updated_at
