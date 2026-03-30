from django.urls import path
from . import views

app_name = 'resume'

urlpatterns = [
    path('', views.resume_page, name='resume_page'),
    path('download/', views.download_resume_pdf, name='download_resume'),
    path('json/', views.resume_json, name='resume_json'),
]