

from django.urls import path
from .views import projects_list, project_detail, home, prediction_demo, make_prediction

urlpatterns = [
    # Home page at root
    path('', home, name='home'),

    # Projects list at /projects/ (since we removed the prefix)
    path('projects/', projects_list, name='projects_list'),

    # Project detail pages
    path('project/<int:project_id>/', project_detail, name='project_detail'),
    path('project/<int:project_id>/predict/', prediction_demo, name='prediction_demo'),
    path('project/<int:project_id>/make-prediction/', make_prediction, name='make_prediction'),
]