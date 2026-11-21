from django.urls import path

from . import views

app_name = 'sports'

urlpatterns = [
    path('', views.page, name='page'),
    path('api/me/', views.me, name='me'),
    path('api/posts/', views.posts, name='posts'),
    path('api/posts/<int:post_id>/', views.delete_post, name='delete_post'),
    path('api/posts/<int:post_id>/sticker/', views.sticker, name='sticker'),
    path('api/posts/<int:post_id>/comments/', views.comments, name='comments'),
]
