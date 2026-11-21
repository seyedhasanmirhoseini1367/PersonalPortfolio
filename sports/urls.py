from django.urls import path

from . import views

app_name = 'sports'

urlpatterns = [
    path('', views.page, name='page'),
    path('api/me/', views.me, name='me'),
    path('api/posts/', views.posts, name='posts'),
    path('api/posts/<int:post_id>/', views.post_detail, name='post_detail'),
    path('api/posts/<int:post_id>/cancel/', views.cancel, name='cancel'),
    path('api/posts/<int:post_id>/sticker/', views.sticker, name='sticker'),
    path('api/posts/<int:post_id>/rsvp/', views.rsvp, name='rsvp'),
    path('api/posts/<int:post_id>/save/', views.save, name='save'),
    path('api/posts/<int:post_id>/comments/', views.comments, name='comments'),
    path('api/comments/<int:comment_id>/', views.delete_comment, name='delete_comment'),
    path('api/users/suggested/', views.suggested, name='suggested'),
    path('api/users/<int:user_id>/', views.profile, name='profile'),
    path('api/users/<int:user_id>/follow/', views.follow, name='follow'),
    path('api/notifications/', views.notifications, name='notifications'),
    path('api/notifications/seen/', views.notifications_seen, name='notifications_seen'),
]
