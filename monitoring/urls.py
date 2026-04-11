from django.urls import path
from . import views

app_name = 'monitoring'


urlpatterns = [
    path('',           views.dashboard,  name='dashboard'),
    path('api/stats/', views.api_stats,  name='api_stats'),
    path('storage/',   views.storage_debug, name='storage_debug'),
    path('debug/storage/', views.storage_debug),
]
