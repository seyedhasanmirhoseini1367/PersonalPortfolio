
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Put the more specific 'profile/edit/' BEFORE the generic 'profile/<str:username>/'
    path('profile/edit/', views.profile_update_view, name='profile_update'),  # This comes first!
    path('profile/', views.ProfileDetailView.as_view(), name='my_profile'),  # This comes second
    path('profile/<str:username>/', views.ProfileDetailView.as_view(), name='profile'),  # This comes last

    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('password-reset/', views.password_reset_request_view, name='password_reset'),
    path('password-reset/confirm/', views.password_reset_confirm_view, name='password_reset_confirm'),
]