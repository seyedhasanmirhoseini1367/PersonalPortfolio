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


def safe_next(request):
    """The ?next= target, but only if it stays on this site (no open redirects)."""
    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.GET.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return ''


def register_view(request):
    """
    User registration view
    """
    if request.user.is_authenticated:
        return redirect(safe_next(request) or 'stories:story_list')

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

            # Redirect to next parameter if it is a safe, same-site address
            return redirect(safe_next(request) or 'stories:story_list')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = CustomUserCreationForm()

    context = {
        'form': form,
        'title': 'Register',
        'next': safe_next(request)
    }
    return render(request, 'accounts/register.html', context)


def login_view(request):
    """
    Custom login view
    """
    if request.user.is_authenticated:
        return redirect(safe_next(request) or 'stories:story_list')

    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            # Allow login with email address
            if '@' in username:
                try:
                    username = CustomUser.objects.get(email__iexact=username).username
                except CustomUser.DoesNotExist:
                    pass
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')

                # Log the login
                logger.info(f'User logged in: {user.username}')

                # Redirect to next parameter if it is a safe, same-site address
                return redirect(safe_next(request) or 'stories:story_list')
        else:
            messages.error(request, 'Invalid username/email or password.')
    else:
        form = CustomAuthenticationForm()

    context = {
        'form': form,
        'title': 'Login',
        'next': safe_next(request)
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

        user_stories = Story.objects.filter(author=user).order_by('-created_at')
        user_comments = Comment.objects.filter(author=user).order_by('-created_at')

        context['user_stories'] = user_stories
        context['user_comments'] = user_comments
        context['is_own_profile'] = (self.request.user == user)
        context['total_views'] = user_stories.aggregate(Sum('view_count'))['view_count__sum'] or 0
        context['recent_comments'] = user_comments[:5]

        is_own = self.request.user == user
        if is_own:
            from content_generator.models import GenerationJob, CompanyProfile
            from django.db.models import Avg
            jobs_qs = GenerationJob.objects.filter(owner=user)
            context['cg_job_count']     = jobs_qs.count()
            context['cg_done_count']    = jobs_qs.filter(status=GenerationJob.STATUS_DONE).count()
            context['cg_avg_score']     = jobs_qs.filter(overall_score__isnull=False).aggregate(
                                              avg=Avg('overall_score'))['avg']
            context['cg_profile_count'] = CompanyProfile.objects.filter(owner=user).count()
            context['cg_recent_jobs']   = (jobs_qs.filter(status=GenerationJob.STATUS_DONE)
                                               .select_related('company_profile')[:4])

        return context


@login_required
def profile_update_view(request):
    """
    Update user profile
    """
    if request.method == 'POST':
        # Add request.FILES to handle file uploads
        user_form = CustomUserChangeForm(
            request.POST,
            request.FILES,  # Important: add this to handle file uploads
            instance=request.user
        )
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
            # Add error messages for debugging
            print("User form errors:", user_form.errors)
            print("Profile form errors:", profile_form.errors)
            messages.error(request, 'Please correct the errors below.')
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
    Email a one-time reset link. The link carries a signed token
    (Django's default_token_generator), so only someone who can read that
    inbox can set a new password. The reply is the same whether or not the
    email belongs to an account.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            for user in CustomUser.objects.filter(email__iexact=email, is_active=True):
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(
                    reverse_lazy('accounts:password_reset_confirm', args=[uid, token])
                )
                try:
                    send_mail(
                        'Reset your HasanAI password',
                        f'Someone asked to reset the password for {user.username}.\n\n'
                        f'Open this link to choose a new password (it works once and expires):\n'
                        f'{reset_url}\n\nIf it was not you, ignore this email.',
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        fail_silently=False,
                    )
                except Exception:
                    logging.getLogger(__name__).exception('Password reset email failed')
            messages.success(
                request,
                'If an account exists with that email, a reset link is on its way.'
            )
            return redirect('accounts:login')
    else:
        form = PasswordResetRequestForm()

    context = {'form': form, 'title': 'Reset Password'}
    return render(request, 'accounts/password_reset.html', context)


def password_reset_confirm_view(request, uidb64, token):
    """
    Set a new password from an emailed link. The token is checked on every
    request and stops working once the password changes.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.contrib.auth.tokens import default_token_generator
    from django.core.exceptions import ValidationError
    from django.utils.encoding import force_str
    from django.utils.http import urlsafe_base64_decode

    try:
        user = CustomUser.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        messages.error(request, 'This reset link is invalid or has expired. Please ask for a new one.')
        return redirect('accounts:password_reset')

    if request.method == 'POST':
        form = SetNewPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password1']
            try:
                validate_password(new_password, user)
            except ValidationError as exc:
                form.add_error('new_password1', exc)
            else:
                user.set_password(new_password)
                user.save()
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
    profile_user = request.user

    user_stories = Story.objects.filter(author=profile_user).order_by('-published_at')
    user_comments = Comment.objects.filter(author=profile_user).order_by('-created_at')
    days_since_join = (timezone.now() - profile_user.date_joined).days
    total_views = user_stories.aggregate(Sum('view_count'))['view_count__sum'] or 0

    context = {
        'profile_user': profile_user,
        'user_stories': user_stories,
        'user_comments': user_comments,
        'recent_stories': user_stories[:5],
        'recent_comments': user_comments[:5],
        'days_since_join': days_since_join,
        'total_views': total_views,
        'title': 'Dashboard',
    }

    if profile_user.is_authenticated:
        from content_generator.models import GenerationJob, CompanyProfile
        from django.db.models import Avg
        jobs_qs = GenerationJob.objects.filter(owner=profile_user)
        context['cg_job_count']     = jobs_qs.count()
        context['cg_done_count']    = jobs_qs.filter(status=GenerationJob.STATUS_DONE).count()
        context['cg_avg_score']     = jobs_qs.filter(overall_score__isnull=False).aggregate(
                                          avg=Avg('overall_score'))['avg']
        context['cg_profile_count'] = CompanyProfile.objects.filter(owner=profile_user).count()
        context['cg_recent_jobs']   = jobs_qs.filter(status=GenerationJob.STATUS_DONE).select_related(
                                          'company_profile')[:5]

    return render(request, 'accounts/dashboard.html', context)