# rag_system/urls.py
from django.urls import path
from . import views

app_name = 'rag_system'

urlpatterns = [
    path('', views.chat_view, name='chat'),
    path('api/query/', views.query_api, name='query_api'),
    path('api/history/', views.chat_history, name='chat_history'),
]