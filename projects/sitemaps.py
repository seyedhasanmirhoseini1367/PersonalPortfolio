from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Projects


class StaticViewSitemap(Sitemap):
    priority   = 0.8
    changefreq = 'weekly'
    protocol   = 'https'

    def items(self):
        return ['home', 'projects_list', 'model_internals:walkthrough_list',
                'resume:resume_page', 'stories:story_list', 'sports:page',
                'kaggle_archive:competition_list', 'contact:contact_page']

    def location(self, item):
        return reverse(item)


class WalkthroughSitemap(Sitemap):
    changefreq = 'monthly'
    protocol   = 'https'
    priority   = 0.7

    def items(self):
        from model_internals.models import Walkthrough
        return Walkthrough.objects.filter(is_published=True)

    def location(self, obj):
        return reverse('model_internals:walkthrough_detail', args=[obj.slug])


class ProjectSitemap(Sitemap):
    changefreq = 'monthly'
    protocol   = 'https'
    priority   = 0.7

    def items(self):
        return Projects.objects.filter(is_public=True)

    def location(self, obj):
        return reverse('project_detail', args=[obj.pk])

    def lastmod(self, obj):
        return obj.updated_at
