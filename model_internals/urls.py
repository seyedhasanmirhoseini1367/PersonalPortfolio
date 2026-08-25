from django.urls import path
from . import views

app_name = 'model_internals'

urlpatterns = [
    path('', views.WalkthroughListView.as_view(), name='walkthrough_list'),
    path('<slug:slug>/', views.WalkthroughDetailView.as_view(), name='walkthrough_detail'),
]
