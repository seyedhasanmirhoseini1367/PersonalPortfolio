from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import DetailView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView
from django.core.mail import send_mail
from django.conf import settings
from django.utils.crypto import get_random_string
from django.utils import timezone
from datetime import timedelta
import logging

from .forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    ProfileUpdateForm,
    PasswordResetRequestForm,
    SetNewPasswordForm, CustomUserChangeForm
)
from .models import CustomUser, UserProfile
from stories.models import Story, Comment

logger = logging.getLogger(__name__)


def register_view(request):
    """
    User registration view
    """
    if request.user.is_authenticated:
        return redirect('stories:story_list')

    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(
                request,
                f'Account created successfully! Welcome, {user.username}!'
            )

            # Log the registration
            logger.info(f'New user registered: {user.username} ({user.email})')

            # Redirect to next parameter if exists
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('stories:story_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()

    context = {
        'form': form,
        'title': 'Register',
        'next': request.GET.get('next', '')
    }
    return render(request, 'accounts/register.html', context)


def login_view(request):
    """
    Custom login view
    """
    if request.user.is_authenticated:
        return redirect('stories:story_list')

    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')

                # Log the login
                logger.info(f'User logged in: {user.username}')

                # Redirect to next parameter if exists
                next_url = request.GET.get('next', '')
                if next_url:
                    return redirect(next_url)
                return redirect('stories:story_list')
        else:
            messages.error(request, 'Invalid username/email or password.')
    else:
        form = CustomAuthenticationForm()

    context = {
        'form': form,
        'title': 'Login',
        'next': request.GET.get('next', '')
    }
    return render(request, 'accounts/login.html', context)


@login_required
def logout_view(request):
    """
    Logout view
    """
    username = request.user.username
    logout(request)
    messages.success(request, 'You have been logged out successfully.')

    # Log the logout
    logger.info(f'User logged out: {username}')

    return redirect('stories:story_list')


class ProfileDetailView(LoginRequiredMixin, DetailView):
    """
    User profile detail view
    """
    model = CustomUser
    template_name = 'accounts/profile_detail.html'
    context_object_name = 'profile_user'

    def get_object(self):
        username = self.kwargs.get('username')
        if username:
            return get_object_or_404(CustomUser, username=username)
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_object()

        # Get user's stories and comments
        context['user_stories'] = Story.objects.filter(author=user).order_by('-created_at')
        context['user_comments'] = Comment.objects.filter(author=user).order_by('-created_at')

        # Check if viewing own profile
        context['is_own_profile'] = (self.request.user == user)

        return context


@login_required
def profile_update_view(request):
    """
    Update user profile
    """
    if request.method == 'POST':
        user_form = CustomUserChangeForm(request.POST, instance=request.user)
        profile_form = ProfileUpdateForm(
            request.POST,
            instance=request.user.profile
        )

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated!')
            return redirect('accounts:profile', username=request.user.username)
    else:
        user_form = CustomUserChangeForm(instance=request.user)
        profile_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'user_form': user_form,
        'profile_form': profile_form,
        'title': 'Edit Profile'
    }
    return render(request, 'accounts/profile_update.html', context)


def password_reset_request_view(request):
    """
    Handle password reset requests
    """
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = CustomUser.objects.get(email=email)

                # Generate reset token (in production, use a proper token system)
                reset_token = get_random_string(32)
                request.session['reset_token'] = reset_token
                request.session['reset_user_id'] = user.id
                request.session['reset_expiry'] = (timezone.now() + timedelta(hours=1)).isoformat()

                # Send email (in production)
                reset_url = request.build_absolute_uri(
                    reverse_lazy('accounts:password_reset_confirm')
                )

                send_mail(
                    'Password Reset Request',
                    f'Click this link to reset your password: {reset_url}',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )

                messages.success(
                    request,
                    'Password reset instructions have been sent to your email.'
                )
                return redirect('accounts:login')

            except CustomUser.DoesNotExist:
                # Don't reveal that the user doesn't exist
                messages.success(
                    request,
                    'If an account exists with that email, you will receive reset instructions.'
                )
                return redirect('accounts:login')
    else:
        form = PasswordResetRequestForm()

    context = {'form': form, 'title': 'Reset Password'}
    return render(request, 'accounts/password_reset.html', context)


def password_reset_confirm_view(request):
    """
    Confirm password reset
    """
    # Check token validity
    reset_token = request.session.get('reset_token')
    user_id = request.session.get('reset_user_id')
    expiry_str = request.session.get('reset_expiry')

    if not all([reset_token, user_id, expiry_str]):
        messages.error(request, 'Invalid or expired reset link.')
        return redirect('accounts:password_reset')

    expiry = timezone.datetime.fromisoformat(expiry_str)
    if timezone.now() > expiry:
        messages.error(request, 'Reset link has expired.')
        return redirect('accounts:password_reset')

    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        messages.error(request, 'Invalid reset link.')
        return redirect('accounts:password_reset')

    if request.method == 'POST':
        form = SetNewPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password1']
            user.set_password(new_password)
            user.save()

            # Clear reset session data
            del request.session['reset_token']
            del request.session['reset_user_id']
            del request.session['reset_expiry']

            messages.success(
                request,
                'Your password has been reset successfully. Please login with your new password.'
            )
            return redirect('accounts:login')
    else:
        form = SetNewPasswordForm()

    context = {'form': form, 'title': 'Set New Password'}
    return render(request, 'accounts/password_reset_confirm.html', context)


# accounts/views.py
@login_required
def dashboard_view(request):
    """User dashboard"""
    profile_user = request.user  # Change this line

    # Get user's stories and comments
    user_stories = Story.objects.filter(author=profile_user).order_by('-published_at')
    user_comments = Comment.objects.filter(author=profile_user).order_by('-created_at')

    # Calculate days since joining
    days_since_join = (timezone.now() - profile_user.date_joined).days

    # Calculate total views
    total_views = user_stories.aggregate(Sum('view_count'))['view_count__sum'] or 0

    context = {
        'profile_user': profile_user,  # Use profile_user consistently
        'user_stories': user_stories,
        'user_comments': user_comments,
        'recent_stories': user_stories[:5],
        'recent_comments': user_comments[:5],
        'days_since_join': days_since_join,
        'total_views': total_views,
        'title': 'Dashboard'
    }
    return render(request, 'accounts/dashboard.html', context)