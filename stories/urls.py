# stories/urls.py - FIXED VERSION
from django.urls import path
from . import views

app_name = 'stories'

urlpatterns = [
    # Story list and browsing
    path('', views.StoryListView.as_view(), name='story_list'),

    # Story CRUD operations
    path('create/', views.StoryCreateView.as_view(), name='create_story'),
    path('story/<slug:slug>/', views.StoryDetailView.as_view(), name='story_detail'),
    path('story/<int:pk>/edit/', views.StoryUpdateView.as_view(), name='story_update'),
    path('story/<int:pk>/delete/', views.StoryDeleteView.as_view(), name='story_delete'),
    path('story/<int:pk>/preview/', views.story_preview, name='story_preview'),

    # User stories
    path('my-stories/', views.UserStoryListView.as_view(), name='user_stories'),

    # Tag views
    path('tag/<slug:slug>/', views.TagStoryListView.as_view(), name='tag_stories'),

    # AJAX actions - Changed to use story ID instead of slug
    path('story/<int:story_id>/comment/', views.add_comment, name='add_comment'),
    path('comment/<int:comment_id>/reply/', views.add_reply, name='add_reply'),
    path('story/<int:story_id>/like/', views.like_story, name='like_story'),

    # Rich-text editor image upload
    path('editor/image-upload/', views.story_image_upload, name='image_upload'),
]