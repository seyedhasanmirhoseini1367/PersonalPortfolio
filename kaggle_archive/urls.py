from django.urls import path
from . import views

app_name = 'kaggle_archive'

urlpatterns = [
    path('', views.CompetitionListView.as_view(), name='competition_list'),
    path('manage/', views.manage_view, name='manage'),
    path('manage/status/<int:job_id>/', views.job_status_view, name='job_status'),
    path('<slug:slug>/', views.CompetitionDetailView.as_view(), name='competition_detail'),
]
