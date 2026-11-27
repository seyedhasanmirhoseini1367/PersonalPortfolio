from django.urls import path

from . import views

app_name = 'journey'

urlpatterns = [
    path('', views.home, name='home'),
    path('language/', views.set_language, name='set_language'),
    path('add/', views.lesson_add, name='lesson_add'),
    path('library/', views.library, name='library'),
    path('progress/', views.progress, name='progress'),
    path('town/', views.town, name='town'),
    path('api/town/', views.api_town, name='api_town'),
    path('api/town/avatar/', views.api_town_avatar, name='api_town_avatar'),
    path('api/town/buy/', views.api_town_buy, name='api_town_buy'),
    path('api/town/scene/<slug:key>/start/', views.api_scene_start, name='api_scene_start'),
    path('api/town/scene/<slug:key>/answer/', views.api_scene_answer, name='api_scene_answer'),
    path('api/town/scene/<slug:key>/save/', views.api_scene_save, name='api_scene_save'),
    path('spaces/new/', views.space_create, name='space_create'),
    path('groups/new/', views.group_create, name='group_create'),
    path('groups/join/', views.group_join, name='group_join'),
    path('g/<str:code>/', views.group, name='group'),
    path('g/<str:code>/leave/', views.group_leave, name='group_leave'),
    path('g/<str:code>/settings/', views.group_settings, name='group_settings'),
    path('g/<str:code>/new/', views.pack_new, name='pack_new'),
    path('g/<str:code>/lessons/new/', views.lesson_create, name='lesson_create'),
    path('g/<str:code>/practice/', views.group_practice, name='group_practice'),
    path('lesson/<int:pk>/', views.pack, name='pack'),
    path('lesson/<int:pk>/status/', views.pack_status, name='pack_status'),
    path('lesson/<int:pk>/edit/', views.pack_edit, name='pack_edit'),
    path('lesson/<int:pk>/material/', views.lesson_material, name='lesson_material'),
    path('lesson/<int:pk>/practice/', views.lesson_practice, name='lesson_practice'),
    path('review/', views.review, name='review'),
    path('mistakes/', views.mistakes, name='mistakes'),
    path('api/due/', views.api_due, name='api_due'),
    path('api/grade/', views.api_grade, name='api_grade'),
]
