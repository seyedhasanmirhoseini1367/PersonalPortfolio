from django.urls import path
from django.http import HttpResponse


def robots_txt(request):
    lines = [
        'User-agent: *',
        'Disallow: /admin/',
        'Disallow: /accounts/login/',
        'Disallow: /accounts/register/',
        'Disallow: /rag/',
        'Allow: /',
        '',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


urlpatterns = [
    path('', robots_txt),
]
