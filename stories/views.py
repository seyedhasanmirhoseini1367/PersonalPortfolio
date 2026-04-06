# stories/views.py - FIXED VERSION
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.db.models import Q, Count, Sum, F
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.paginator import Paginator
from .models import Story, Comment, Tag, StoryView, StoryLike
from .forms import StoryForm, CommentForm, StorySearchForm, ReplyForm
from django.utils import timezone
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
import json
from datetime import timedelta


class StoryListView(ListView):
    """View for listing all published stories."""
    model = Story
    template_name = 'stories/story_list.html'
    context_object_name = 'stories'
    paginate_by = 10

    def get_queryset(self):
        queryset = Story.objects.filter(
            status=Story.Status.PUBLISHED,
            published_at__lte=timezone.now()
        ).select_related('author').prefetch_related('tags')

        # Apply search filters
        form = StorySearchForm(self.request.GET)
        if form.is_valid():
            query = form.cleaned_data.get('query')
            tag = form.cleaned_data.get('tag')
            author = form.cleaned_data.get('author')
            sort_by = form.cleaned_data.get('sort_by') or '-published_at'

            if query:
                queryset = queryset.filter(
                    Q(title__icontains=query) |
                    Q(content__icontains=query) |
                    Q(excerpt__icontains=query)
                )

            if tag:
                queryset = queryset.filter(tags=tag)

            if author:
                queryset = queryset.filter(author=author)

            queryset = queryset.order_by(sort_by)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = StorySearchForm(self.request.GET)
        context['featured_stories'] = Story.objects.filter(
            status=Story.Status.PUBLISHED,
            is_featured=True,
            published_at__lte=timezone.now()
        )[:3]
        context['popular_tags'] = Tag.objects.annotate(
            num_stories=Count('stories')
        ).filter(num_stories__gt=0).order_by('-num_stories')[:10]
        return context


class StoryDetailView(DetailView):
    """View for displaying a single story."""
    model = Story
    template_name = 'stories/story_detail.html'
    context_object_name = 'story'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return Story.objects.select_related('author').prefetch_related(
            'tags',
            'comments__author',
            'comments__replies__author'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        story = context['story']

        # Track view with anti-duplicate logic
        self.track_story_view(story)

        # Add comment form
        context['comment_form'] = CommentForm()

        # Get approved comments with their replies
        context['comments'] = story.comments.filter(
            is_approved=True,
            parent__isnull=True
        ).select_related('author').prefetch_related(
            'replies__author'
        ).order_by('-created_at')

        # Get related stories
        tags = story.tags.all()
        context['related_stories'] = Story.objects.filter(
            tags__in=tags,
            status=Story.Status.PUBLISHED
        ).exclude(id=story.id).distinct()[:4]

        # Check if user has liked the story
        if self.request.user.is_authenticated:
            context['story'].user_has_liked = StoryLike.objects.filter(
                story=story,
                user=self.request.user
            ).exists()
        else:
            context['story'].user_has_liked = False

        return context

    def track_story_view(self, story):
        """Track story view with anti-duplicate logic."""
        ip_address = self.request.META.get('REMOTE_ADDR')
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')

        if self.should_count_view(story, ip_address):
            StoryView.objects.create(
                story=story,
                user=self.request.user if self.request.user.is_authenticated else None,
                ip_address=ip_address,
                user_agent=user_agent
            )

            Story.objects.filter(id=story.id).update(view_count=F('view_count') + 1)
            story.refresh_from_db(fields=['view_count'])
            self.mark_view_counted(story)

    def should_count_view(self, story, ip_address):
        """Determine if this view should be counted."""
        session = self.request.session
        session_key = f'viewed_story_{story.id}'

        if session.get(session_key, False):
            return False

        one_hour_ago = timezone.now() - timedelta(hours=1)

        if self.request.user.is_authenticated:
            recent_view = StoryView.objects.filter(
                story=story,
                user=self.request.user,
                viewed_at__gte=one_hour_ago
            ).exists()
            if recent_view:
                return False

        recent_ip_view = StoryView.objects.filter(
            story=story,
            ip_address=ip_address,
            viewed_at__gte=one_hour_ago
        ).exists()

        return not recent_ip_view

    def mark_view_counted(self, story):
        """Mark story as viewed in current session."""
        session = self.request.session
        session_key = f'viewed_story_{story.id}'
        session[session_key] = True
        session.set_expiry(3600)
        session.modified = True


class StoryCreateView(LoginRequiredMixin, CreateView):
    """View for creating a new story."""
    model = Story
    form_class = StoryForm
    template_name = 'stories/story_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['author'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.author = self.request.user
        messages.success(self.request, 'Your story has been created successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('stories:story_detail', kwargs={'slug': self.object.slug})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Create New Story'
        return context


class StoryUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """View for updating an existing story."""
    model = Story
    form_class = StoryForm
    template_name = 'stories/story_form.html'

    def test_func(self):
        story = self.get_object()
        return self.request.user == story.author or self.request.user.is_staff

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['author'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Your story has been updated successfully!')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('stories:story_detail', kwargs={'slug': self.object.slug})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edit Story'
        return context


class StoryDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """View for deleting a story."""
    model = Story
    template_name = 'stories/story_confirm_delete.html'
    success_url = reverse_lazy('stories:story_list')

    def test_func(self):
        story = self.get_object()
        return self.request.user == story.author or self.request.user.is_staff

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Story has been deleted successfully!')
        return super().delete(request, *args, **kwargs)


class UserStoryListView(LoginRequiredMixin, ListView):
    """View for listing stories by the current user."""
    model = Story
    template_name = 'stories/user_stories.html'
    context_object_name = 'stories'
    paginate_by = 10

    def get_queryset(self):
        return Story.objects.filter(
            author=self.request.user
        ).order_by('-created_at')


class TagStoryListView(ListView):
    """View for listing stories by tag."""
    model = Story
    template_name = 'stories/tag_stories.html'
    context_object_name = 'stories'
    paginate_by = 10

    def get_queryset(self):
        self.tag = get_object_or_404(Tag, slug=self.kwargs.get('slug'))
        return Story.objects.filter(
            tags=self.tag,
            status=Story.Status.PUBLISHED,
            published_at__lte=timezone.now()
        ).order_by('-published_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tag'] = self.tag
        return context


@login_required
def add_comment(request, story_id):
    """
    Handle comment submission via AJAX or regular POST
    """
    story = get_object_or_404(Story, id=story_id)

    if not story.allow_comments:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Comments are disabled for this story.'}, status=403)
        messages.error(request, 'Comments are disabled for this story.')
        return redirect('stories:story_detail', slug=story.slug)

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()

        if not content:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Comment content cannot be empty.'}, status=400)
            messages.error(request, 'Comment content cannot be empty.')
            return redirect('stories:story_detail', slug=story.slug)

        # Create comment
        comment = Comment.objects.create(
            story=story,
            author=request.user,
            content=content,
            is_approved=True  # Auto-approve or set to False for moderation
        )

        # Update user's comment count
        if hasattr(request.user, 'profile'):
            request.user.profile.increment_comment_count()

        # AJAX response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'comment_id': comment.id,
                'author': comment.author.username,
                'content': comment.content,
                'created_at': comment.created_at.strftime('%b %d, %Y %I:%M %p')
            })

        messages.success(request, 'Your comment has been posted!')
        return redirect('stories:story_detail', slug=story.slug)

    return redirect('stories:story_detail', slug=story.slug)


@require_POST
@login_required
def add_reply(request, comment_id):
    """
    Handle reply submission via AJAX or regular POST
    """
    parent_comment = get_object_or_404(Comment, id=comment_id)
    story = parent_comment.story

    if not story.allow_comments:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Comments are disabled for this story.'}, status=403)
        messages.error(request, 'Comments are disabled for this story.')
        return redirect('stories:story_detail', slug=story.slug)

    content = request.POST.get('content', '').strip()

    if not content:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Reply content cannot be empty.'}, status=400)
        messages.error(request, 'Reply content cannot be empty.')
        return redirect('stories:story_detail', slug=story.slug)

    # Create reply
    reply = Comment.objects.create(
        story=story,
        author=request.user,
        content=content,
        parent=parent_comment,
        is_approved=True  # Auto-approve or set to False for moderation
    )

    # Update user's comment count
    if hasattr(request.user, 'profile'):
        request.user.profile.increment_comment_count()

    # AJAX response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'comment_id': reply.id,
            'author': reply.author.username,
            'content': reply.content,
            'created_at': reply.created_at.strftime('%b %d, %Y %I:%M %p'),
            'parent_id': parent_comment.id
        })

    messages.success(request, 'Your reply has been posted!')
    return redirect('stories:story_detail', slug=story.slug)


@require_POST
@login_required
def like_story(request, story_id):
    """
    Handle story like/unlike via AJAX
    """
    story = get_object_or_404(Story, id=story_id)

    # Check if user already liked the story
    like_exists = StoryLike.objects.filter(
        story=story,
        user=request.user
    ).exists()

    if like_exists:
        # Unlike the story
        StoryLike.objects.filter(story=story, user=request.user).delete()
        story.likes_count = F('likes_count') - 1
        story.save(update_fields=['likes_count'])
        story.refresh_from_db()
        liked = False
    else:
        # Like the story
        StoryLike.objects.create(story=story, user=request.user)
        story.likes_count = F('likes_count') + 1
        story.save(update_fields=['likes_count'])
        story.refresh_from_db()
        liked = True

    return JsonResponse({
        'success': True,
        'likes': story.likes_count,
        'liked': liked
    })


@require_POST
@login_required
def story_image_upload(request):
    """
    Accept an image file upload from the Quill rich-text editor.
    Returns JSON: { "url": "/media/stories/inline/filename.jpg" }
    """
    import os
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile

    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'error': 'No image provided'}, status=400)

    ext = os.path.splitext(image.name)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return JsonResponse({'error': 'Only JPG, PNG, GIF and WEBP images are allowed'}, status=400)

    if image.size > 5 * 1024 * 1024:   # 5 MB limit
        return JsonResponse({'error': 'Image must be smaller than 5 MB'}, status=400)

    path = default_storage.save(f'stories/inline/{image.name}', ContentFile(image.read()))
    url  = request.build_absolute_uri(default_storage.url(path))
    return JsonResponse({'url': url})


def story_preview(request, pk):
    """
    Preview a story (for authors and staff)
    """
    story = get_object_or_404(Story, pk=pk)

    # Only allow preview for authors and staff
    if not (request.user == story.author or request.user.is_staff):
        return HttpResponseForbidden("You don't have permission to preview this story.")

    context = {
        'story': story,
        'preview_mode': True,
        'comments': story.comments.filter(
            is_approved=True,
            parent__isnull=True
        ).select_related('author').prefetch_related('replies__author').order_by('-created_at')
    }
    return render(request, 'stories/story_detail.html', context)