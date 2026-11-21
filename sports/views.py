"""The sports social-app prototype: the page itself plus a small JSON API.

The page is one self-contained HTML file (static/sports/index.html). It calls
these endpoints with the visitor's normal site session, so signing up and
logging in use the portfolio's existing accounts.
"""
import json
from collections import Counter

from django.conf import settings
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .models import SPORT_STICKERS, PostComment, PostSticker, SportPost

PAGE_PATH = settings.BASE_DIR / 'static' / 'sports' / 'index.html'
FEED_LIMIT = 50


@ensure_csrf_cookie
@require_GET
def page(request):
    return HttpResponse(PAGE_PATH.read_text(encoding='utf-8'), content_type='text/html; charset=utf-8')


def display_name(user):
    name = (user.get_full_name() or '').strip()
    if name:
        return name
    if user.username and '@' not in user.username:
        return user.username
    return (user.email or 'Player').split('@')[0]


def initials(name):
    parts = [p for p in name.replace('.', ' ').replace('_', ' ').split() if p]
    letters = ''.join(p[0] for p in parts[:2]) or name[:2]
    return letters.upper()


def user_json(user):
    name = display_name(user)
    return {'id': user.id, 'name': name, 'ini': initials(name)}


def error(message, status):
    return JsonResponse({'error': message}, status=status)


def login_required_json(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error('Log in to do that.', 401)
        return view(request, *args, **kwargs)
    return wrapped


def read_json(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None


def post_json(post, user):
    stickers = list(post.stickers.all())
    counts = Counter(s.sticker for s in stickers)
    mine = next((s.sticker for s in stickers if user.is_authenticated and s.user_id == user.id), None)
    return {
        'id': post.id,
        'author': user_json(post.author),
        'sport': post.sport,
        'text': post.text,
        'created_at': post.created_at.isoformat(),
        'stickers': len(stickers),
        'top': [k for k, _ in counts.most_common(3)],
        'mine': mine,
        'comments': post.n_comments,
        'can_delete': user.is_authenticated and post.author_id == user.id,
    }


def posts_queryset():
    return (SportPost.objects.select_related('author')
            .prefetch_related('stickers')
            .annotate(n_comments=Count('comments')))


@require_GET
def me(request):
    login = reverse('accounts:login') + '?next=/sports/'
    register = reverse('accounts:register') + '?next=/sports/'
    logout = reverse('accounts:logout')
    if not request.user.is_authenticated:
        return JsonResponse({'authenticated': False, 'login_url': login, 'register_url': register})
    return JsonResponse({'authenticated': True, 'user': user_json(request.user), 'logout_url': logout})


@require_http_methods(['GET', 'POST'])
def posts(request):
    if request.method == 'GET':
        feed = posts_queryset()[:FEED_LIMIT]
        return JsonResponse({'posts': [post_json(p, request.user) for p in feed]})
    return create_post(request)


@login_required_json
def create_post(request):
    data = read_json(request)
    if data is None:
        return error('Bad request.', 400)
    sport = data.get('sport')
    text = (data.get('text') or '').strip()
    if sport not in SPORT_STICKERS:
        return error('Pick a sport.', 400)
    if not text:
        return error('Write something first.', 400)
    if len(text) > 280:
        return error('Keep it under 280 characters.', 400)
    post = SportPost.objects.create(author=request.user, sport=sport, text=text)
    return JsonResponse({'post': post_json(posts_queryset().get(pk=post.pk), request.user)}, status=201)


@require_http_methods(['DELETE'])
@login_required_json
def delete_post(request, post_id):
    post = get_object_or_404(SportPost, pk=post_id)
    if post.author_id != request.user.id:
        return error('You can only delete your own posts.', 403)
    post.delete()
    return JsonResponse({'deleted': post_id})


@require_http_methods(['POST'])
@login_required_json
def sticker(request, post_id):
    """Set the user's sticker on a post; picking the same one again removes it."""
    post = get_object_or_404(SportPost, pk=post_id)
    data = read_json(request)
    if data is None:
        return error('Bad request.', 400)
    key = data.get('sticker')
    if key not in SPORT_STICKERS[post.sport]:
        return error('That sticker is not available for this sport.', 400)
    existing = PostSticker.objects.filter(post=post, user=request.user).first()
    if existing and existing.sticker == key:
        existing.delete()
    elif existing:
        existing.sticker = key
        existing.save(update_fields=['sticker'])
    else:
        PostSticker.objects.create(post=post, user=request.user, sticker=key)
    return JsonResponse({'post': post_json(posts_queryset().get(pk=post.pk), request.user)})


@require_http_methods(['GET', 'POST'])
def comments(request, post_id):
    post = get_object_or_404(SportPost, pk=post_id)
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return error('Log in to comment.', 401)
        data = read_json(request)
        text = ((data or {}).get('text') or '').strip()
        if not text:
            return error('Write a comment first.', 400)
        if len(text) > 500:
            return error('Keep it under 500 characters.', 400)
        PostComment.objects.create(post=post, author=request.user, text=text)
    items = post.comments.select_related('author')
    return JsonResponse({'comments': [
        {'id': c.id, 'author': user_json(c.author), 'text': c.text, 'created_at': c.created_at.isoformat()}
        for c in items
    ]})
