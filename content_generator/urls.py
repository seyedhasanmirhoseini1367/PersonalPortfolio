from django.urls import path
from . import views

app_name = 'content_generator'

urlpatterns = [
    # Generator
    path('',                                    views.demo_form,       name='form'),
    path('generate/',                           views.submit_job,      name='submit'),
    path('group-status/<uuid:group_id>/',       views.group_status,    name='group_status'),
    path('group-result/<uuid:group_id>/',       views.group_result,    name='group_result'),
    path('history/',                            views.content_history, name='history'),

    # Job actions
    path('job/<uuid:job_id>/edit/',             views.edit_job,        name='edit_job'),
    path('job/<uuid:job_id>/approve/',          views.approve_job,     name='approve_job'),
    path('job/<uuid:job_id>/rerun/',            views.rerun_job,       name='rerun_job'),
    path('job/<uuid:job_id>/publish/',          views.publish_cms,     name='publish_cms'),

    # Company profiles (client-owned)
    path('profiles/',                           views.profile_list,           name='profile_list'),
    path('profiles/create/',                    views.profile_create,         name='profile_create'),
    path('profiles/<int:pk>/edit/',             views.profile_edit,           name='profile_edit'),
    path('profiles/<int:pk>/delete/',           views.profile_delete,         name='profile_delete'),

    # Client Workspace
    path('workspace/',                              views.workspace,              name='workspace'),
    path('workspace/company/edit/',                 views.workspace_profile_edit, name='workspace_profile_edit'),
    path('workspace/document/upload/',              views.document_upload,        name='document_upload'),
    path('workspace/document/<int:pk>/delete/',     views.document_delete,        name='document_delete'),
    path('workspace/service/add/',                  views.service_create,         name='service_create'),
    path('workspace/service/<int:pk>/edit/',        views.service_edit,           name='service_edit'),
    path('workspace/service/<int:pk>/delete/',      views.service_delete,         name='service_delete'),
]
