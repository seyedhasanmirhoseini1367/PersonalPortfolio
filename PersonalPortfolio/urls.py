from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from projects.sitemaps import StaticViewSitemap, ProjectSitemap
from stories.sitemaps import StorySitemap

sitemaps = {
    'static':   StaticViewSitemap,
    'projects': ProjectSitemap,
    'stories':  StorySitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', include('projects.urls')),
    path('contact/', include('contact.urls')),
    path('resume/', include('resume.urls')),
    path('rag/', include('rag_system.urls')),
    path('accounts/', include('accounts.urls')),
    path('stories/',    include('stories.urls')),
    path('monitoring/', include('monitoring.urls')),

    # SEO
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', include('projects.robots_urls')),
]

# Error handlers (active when DEBUG=False)
handler404 = 'projects.views.error_404'
handler500 = 'projects.views.error_500'

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Always serve media files (backed by persistent /home/media on Azure)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
