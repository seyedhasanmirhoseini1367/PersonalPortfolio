from django.urls import path
from .views import (
    projects_list, project_detail, home,
    prediction_demo, file_prediction, make_prediction, interpret_prediction,
    add_project_comment,
)
from .api import api_model_list, api_model_detail, api_predict

urlpatterns = [
    path('', home, name='home'),
    path('projects/', projects_list, name='projects_list'),
    path('project/<int:project_id>/', project_detail, name='project_detail'),
    path('project/<int:project_id>/predict/', prediction_demo, name='prediction_demo'),
    path('project/<int:project_id>/file-prediction/', file_prediction, name='file_prediction'),
    path('project/<int:project_id>/make-prediction/', make_prediction, name='make_prediction'),
    path('project/<int:project_id>/interpret/', interpret_prediction, name='interpret_prediction'),
    path('project/<int:project_id>/comment/', add_project_comment, name='add_project_comment'),

    # Public REST API
    path('api/models/',                       api_model_list,   name='api_model_list'),
    path('api/models/<int:project_id>/',      api_model_detail, name='api_model_detail'),
    path('api/models/<int:project_id>/predict/', api_predict,   name='api_predict'),
]
