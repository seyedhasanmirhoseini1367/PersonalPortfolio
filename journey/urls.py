from django.urls import path

from . import views

app_name = 'journey'

urlpatterns = [
    path('', views.home, name='home'),
    path('groups/new/', views.group_create, name='group_create'),
    path('groups/join/', views.group_join, name='group_join'),
    path('g/<str:code>/', views.group, name='group'),
    path('g/<str:code>/leave/', views.group_leave, name='group_leave'),
    path('g/<str:code>/new/', views.pack_new, name='pack_new'),
    path('lesson/<int:pk>/', views.pack, name='pack'),
    path('lesson/<int:pk>/status/', views.pack_status, name='pack_status'),
    path('lesson/<int:pk>/edit/', views.pack_edit, name='pack_edit'),
    path('review/', views.review, name='review'),
    path('mistakes/', views.mistakes, name='mistakes'),
    path('api/due/', views.api_due, name='api_due'),
    path('api/grade/', views.api_grade, name='api_grade'),
]
