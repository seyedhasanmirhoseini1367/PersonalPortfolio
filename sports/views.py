"""The sports social app: the page itself plus a small JSON API.

The page is one self-contained HTML file (static/sports/index.html). It calls
these endpoints with the visitor's normal site session, so signing up and
logging in use the portfolio's existing accounts.
"""
import json
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from django.contrib.auth import get_user_model

from .models import (SPORT_STICKERS, EventRSVP, Follow, PostComment, PostSticker,
                     SavedPost, SportPost, SportsProfile)

User = get_user_model()

PAGE_PATH = settings.BASE_DIR / 'static' / 'sports' / 'index.html'
PAGE_SIZE = 20
MAX_COMMENTS = 200
GOING_SHOWN = 12

# (max actions, window in seconds) per user. Generous for real use, stops floods.
LIMITS = {
    'post': (10, 600),
    'comment': (40, 600),
    'react': (200, 600),
    'follow': (100, 600),
}


# ── helpers ──────────────────────────────────────────────────────────────────

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


def not_found():
    return error('This post no longer exists.', 404)


def login_required_json(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return error('Log in to do that.', 401)
        return view(request, *args, **kwargs)
    return wrapped


def read_json(request):
    """The request body as a dict, or None if it isn't a JSON object."""
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def text_field(data, key):
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ''


def throttled(user, action):
    """True if this user has used up their allowance for this action."""
    limit, window = LIMITS[action]
    key = f'sports:{action}:{user.id}'
    if cache.add(key, 1, window):
        return False
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.add(key, 1, window)
        return False
    return count > limit


def slow_down():
    return error("You're going a bit fast. Try again in a few minutes.", 429)


def get_post(post_id):
    return SportPost.objects.filter(pk=post_id).select_related('author').first()


# ── serialising posts ────────────────────────────────────────────────────────

def posts_queryset():
    # order_by is needed: Meta.ordering is ignored once annotate() adds a GROUP BY.
    return (SportPost.objects.select_related('author')
            .prefetch_related('stickers', 'rsvps__user')
            .annotate(n_comments=Count('comments', distinct=True))
            .order_by('-created_at', '-id'))


def viewer_context(user, posts):
    if not user.is_authenticated:
        return {'saved': set(), 'following': set()}
    ids = [p.id for p in posts]
    return {
        'saved': set(SavedPost.objects.filter(user=user, post_id__in=ids).values_list('post_id', flat=True)),
        'following': set(Follow.objects.filter(follower=user).values_list('following_id', flat=True)),
    }


def event_json(post, user):
    rsvps = list(post.rsvps.all())  # prefetched, in join order
    cap = post.capacity
    going = rsvps if cap is None else rsvps[:cap]
    waiting = [] if cap is None else rsvps[cap:]
    me = None
    if user.is_authenticated:
        if any(r.user_id == user.id for r in going):
            me = 'in'
        elif any(r.user_id == user.id for r in waiting):
            me = 'waitlist'
    return {
        'at': post.event_at.isoformat() if post.event_at else None,
        'place': post.place,
        'capacity': cap,
        'going_count': len(going),
        'waitlist_count': len(waiting),
        'going': [user_json(r.user) for r in going[:GOING_SHOWN]],
        'me': me,
        'past': bool(post.event_at and post.event_at < timezone.now()),
    }


def post_json(post, user, ctx):
    stickers = list(post.stickers.all())
    counts = Counter(s.sticker for s in stickers)
    mine = next((s.sticker for s in stickers if user.is_authenticated and s.user_id == user.id), None)
    data = {
        'id': post.id,
        'author': user_json(post.author),
        'sport': post.sport,
        'kind': post.kind,
        'text': post.text,
        'created_at': post.created_at.isoformat(),
        'stickers': len(stickers),
        'top': [k for k, _ in counts.most_common(3)],
        'mine': mine,
        'comments': post.n_comments,
        'can_delete': user.is_authenticated and post.author_id == user.id,
        'saved': post.id in ctx['saved'],
        'author_followed': post.author_id in ctx['following'],
    }
    if post.kind == SportPost.KIND_EVENT:
        data['event'] = event_json(post, user)
    return data


def one_post(post_id, user):
    post = posts_queryset().get(pk=post_id)
    return post_json(post, user, viewer_context(user, [post]))


# ── endpoints ────────────────────────────────────────────────────────────────

def notifications_for(user):
    """Things other people did to this user's posts, plus new followers, newest first."""
    mine = SportPost.objects.filter(author=user)
    items = []
    for s in (PostSticker.objects.filter(post__in=mine).exclude(user=user)
              .select_related('user', 'post').order_by('-created_at')[:30]):
        items.append({'type': 'sticker', 'user': user_json(s.user), 'post_id': s.post_id,
                      'post_text': s.post.text[:60], 'sticker': s.sticker, 'at': s.created_at})
    for c in (PostComment.objects.filter(post__in=mine).exclude(author=user)
              .select_related('author', 'post').order_by('-created_at')[:30]):
        items.append({'type': 'comment', 'user': user_json(c.author), 'post_id': c.post_id,
                      'post_text': c.post.text[:60], 'text': c.text[:80], 'at': c.created_at})
    for r in (EventRSVP.objects.filter(post__in=mine).exclude(user=user)
              .select_related('user', 'post').order_by('-created_at')[:30]):
        items.append({'type': 'rsvp', 'user': user_json(r.user), 'post_id': r.post_id,
                      'post_text': r.post.text[:60], 'at': r.created_at})
    for f in Follow.objects.filter(following=user).select_related('follower').order_by('-created_at')[:30]:
        items.append({'type': 'follow', 'user': user_json(f.follower), 'at': f.created_at})
    items.sort(key=lambda i: i['at'], reverse=True)
    return items[:30]


def unread_count(user):
    profile = SportsProfile.objects.filter(user=user).first()
    seen = profile.notifications_seen_at if profile else None
    return sum(1 for i in notifications_for(user) if seen is None or i['at'] > seen)


@require_GET
def me(request):
    login = reverse('accounts:login') + '?next=/sports/'
    register = reverse('accounts:register') + '?next=/sports/'
    if not request.user.is_authenticated:
        return JsonResponse({'authenticated': False, 'login_url': login, 'register_url': register})
    return JsonResponse({
        'authenticated': True,
        'user': user_json(request.user),
        'logout_url': reverse('accounts:logout'),
        'edit_profile_url': reverse('accounts:profile_update'),
        'unread': unread_count(request.user),
    })


@require_http_methods(['GET', 'POST'])
def posts(request):
    if request.method == 'POST':
        return create_post(request)
    qs = posts_queryset()
    sport = request.GET.get('sport')
    if sport in SPORT_STICKERS:
        qs = qs.filter(sport=sport)
    if request.GET.get('kind') == 'event':
        qs = qs.filter(kind=SportPost.KIND_EVENT)
    author = request.GET.get('author', '')
    if author.isdigit():
        qs = qs.filter(author_id=int(author))
    if request.GET.get('following') == '1':
        if not request.user.is_authenticated:
            return error('Log in to see who you follow.', 401)
        qs = qs.filter(author__sport_followers__follower=request.user)
    if request.GET.get('saved') == '1':
        if not request.user.is_authenticated:
            return error('Log in to see your saved posts.', 401)
        qs = qs.filter(saves__user=request.user)
    before = request.GET.get('before', '')
    if before.isdigit():
        pivot = SportPost.objects.filter(pk=int(before)).values_list('created_at', flat=True).first()
        if pivot:
            qs = qs.filter(created_at__lte=pivot).exclude(pk__gte=int(before), created_at=pivot)
    page_posts = list(qs[:PAGE_SIZE + 1])
    more = len(page_posts) > PAGE_SIZE
    page_posts = page_posts[:PAGE_SIZE]
    ctx = viewer_context(request.user, page_posts)
    return JsonResponse({
        'posts': [post_json(p, request.user, ctx) for p in page_posts],
        'next': page_posts[-1].id if more else None,
    })


@login_required_json
def create_post(request):
    data = read_json(request)
    if data is None:
        return error('Bad request.', 400)
    sport = data.get('sport')
    text = text_field(data, 'text')
    kind = data.get('kind', SportPost.KIND_POST)
    if not isinstance(sport, str) or sport not in SPORT_STICKERS:
        return error('Pick a sport.', 400)
    if kind not in (SportPost.KIND_POST, SportPost.KIND_EVENT):
        return error('Bad request.', 400)
    if not text:
        return error('Write something first.', 400)
    if len(text) > 280:
        return error('Keep it under 280 characters.', 400)
    fields = {}
    if kind == SportPost.KIND_EVENT:
        at = parse_datetime(text_field(data, 'event_at'))
        if at is None:
            return error('Pick a date and time for the event.', 400)
        if timezone.is_naive(at):
            at = timezone.make_aware(at)
        now = timezone.now()
        if at < now - timedelta(hours=1) or at > now + timedelta(days=366):
            return error('Pick a time between now and a year from now.', 400)
        place = text_field(data, 'place')
        if len(place) > 80:
            return error('Keep the place under 80 characters.', 400)
        capacity = data.get('capacity')
        if capacity in (None, '', 0):
            capacity = None
        elif not isinstance(capacity, int) or isinstance(capacity, bool) or not 2 <= capacity <= 200:
            return error('Spots must be a number from 2 to 200.', 400)
        fields = {'event_at': at, 'place': place, 'capacity': capacity}
    if throttled(request.user, 'post'):
        return slow_down()
    post = SportPost.objects.create(author=request.user, sport=sport, text=text, kind=kind, **fields)
    if kind == SportPost.KIND_EVENT:
        EventRSVP.objects.create(post=post, user=request.user)  # the organiser is going
    return JsonResponse({'post': one_post(post.pk, request.user)}, status=201)


@require_http_methods(['DELETE'])
@login_required_json
def delete_post(request, post_id):
    post = get_post(post_id)
    if post is None:
        return not_found()
    if post.author_id != request.user.id:
        return error('You can only delete your own posts.', 403)
    post.delete()
    return JsonResponse({'deleted': post_id})


@require_http_methods(['POST'])
@login_required_json
def sticker(request, post_id):
    """Set the user's sticker on a post; picking the same one again removes it."""
    post = get_post(post_id)
    if post is None:
        return not_found()
    data = read_json(request)
    if data is None:
        return error('Bad request.', 400)
    key = data.get('sticker')
    if not isinstance(key, str) or key not in SPORT_STICKERS[post.sport]:
        return error('That sticker is not available for this sport.', 400)
    if throttled(request.user, 'react'):
        return slow_down()
    try:
        with transaction.atomic():
            existing = PostSticker.objects.select_for_update().filter(post=post, user=request.user).first()
            if existing and existing.sticker == key:
                existing.delete()
            elif existing:
                existing.sticker = key
                existing.save(update_fields=['sticker'])
            else:
                PostSticker.objects.create(post=post, user=request.user, sticker=key)
    except IntegrityError:
        pass  # a double tap raced us; the first request already saved it
    return JsonResponse({'post': one_post(post.pk, request.user)})


@require_http_methods(['POST'])
@login_required_json
def rsvp(request, post_id):
    post = get_post(post_id)
    if post is None:
        return not_found()
    if post.kind != SportPost.KIND_EVENT:
        return error('This post is not an event.', 400)
    data = read_json(request)
    if data is None or not isinstance(data.get('going'), bool):
        return error('Bad request.', 400)
    if throttled(request.user, 'react'):
        return slow_down()
    if data['going']:
        if post.event_at and post.event_at < timezone.now():
            return error('This event has already happened.', 400)
        try:
            EventRSVP.objects.get_or_create(post=post, user=request.user)
        except IntegrityError:
            pass
    else:
        EventRSVP.objects.filter(post=post, user=request.user).delete()
    return JsonResponse({'post': one_post(post.pk, request.user)})


@require_http_methods(['POST'])
@login_required_json
def save(request, post_id):
    post = get_post(post_id)
    if post is None:
        return not_found()
    deleted, _ = SavedPost.objects.filter(user=request.user, post=post).delete()
    if not deleted:
        try:
            SavedPost.objects.create(user=request.user, post=post)
        except IntegrityError:
            pass
    return JsonResponse({'saved': not deleted})


def comment_json(c, user, post):
    can_delete = user.is_authenticated and user.id in (c.author_id, post.author_id)
    return {'id': c.id, 'author': user_json(c.author), 'text': c.text,
            'created_at': c.created_at.isoformat(), 'can_delete': can_delete}


@require_http_methods(['GET', 'POST'])
def comments(request, post_id):
    post = get_post(post_id)
    if post is None:
        return not_found()
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return error('Log in to comment.', 401)
        data = read_json(request)
        if data is None:
            return error('Bad request.', 400)
        text = text_field(data, 'text')
        if not text:
            return error('Write a comment first.', 400)
        if len(text) > 500:
            return error('Keep it under 500 characters.', 400)
        if post.comments.count() >= MAX_COMMENTS:
            return error('This post has reached its comment limit.', 400)
        if throttled(request.user, 'comment'):
            return slow_down()
        PostComment.objects.create(post=post, author=request.user, text=text)
    items = post.comments.select_related('author')[:MAX_COMMENTS]
    reactions = post.stickers.select_related('user').order_by('-created_at')
    return JsonResponse({
        'comments': [comment_json(c, request.user, post) for c in items],
        'reactions': [{'user': user_json(s.user), 'sticker': s.sticker} for s in reactions],
    })


@require_http_methods(['DELETE'])
@login_required_json
def delete_comment(request, comment_id):
    comment = PostComment.objects.select_related('post').filter(pk=comment_id).first()
    if comment is None:
        return error('This comment no longer exists.', 404)
    if request.user.id not in (comment.author_id, comment.post.author_id):
        return error('You can only delete your own comments.', 403)
    comment.delete()
    return JsonResponse({'deleted': comment_id})


@require_GET
def profile(request, user_id):
    person = User.objects.filter(pk=user_id, is_active=True).first()
    if person is None:
        return error('This player no longer exists.', 404)
    me_ = request.user
    received = PostSticker.objects.filter(post__author=person).exclude(user=person).count()
    return JsonResponse({
        'user': user_json(person),
        'is_me': me_.is_authenticated and me_.id == person.id,
        'posts': SportPost.objects.filter(author=person).count(),
        'followers': Follow.objects.filter(following=person).count(),
        'following': Follow.objects.filter(follower=person).count(),
        'stickers_received': received,
        'i_follow': me_.is_authenticated and Follow.objects.filter(follower=me_, following=person).exists(),
        'sports': [s for s, _ in Counter(SportPost.objects.filter(author=person)
                                         .values_list('sport', flat=True)).most_common(3)],
    })


@require_http_methods(['POST'])
@login_required_json
def follow(request, user_id):
    person = User.objects.filter(pk=user_id, is_active=True).first()
    if person is None:
        return error('This player no longer exists.', 404)
    if person.id == request.user.id:
        return error("You can't follow yourself.", 400)
    if throttled(request.user, 'follow'):
        return slow_down()
    deleted, _ = Follow.objects.filter(follower=request.user, following=person).delete()
    if not deleted:
        try:
            Follow.objects.create(follower=request.user, following=person)
        except IntegrityError:
            pass
    return JsonResponse({'following': not deleted,
                         'followers': Follow.objects.filter(following=person).count()})


@require_GET
@login_required_json
def notifications(request):
    profile_ = SportsProfile.objects.filter(user=request.user).first()
    seen = profile_.notifications_seen_at if profile_ else None
    items = notifications_for(request.user)
    for i in items:
        i['unread'] = seen is None or i['at'] > seen
        i['at'] = i['at'].isoformat()
    return JsonResponse({'items': items, 'unread': sum(i['unread'] for i in items)})


@require_http_methods(['POST'])
@login_required_json
def notifications_seen(request):
    SportsProfile.objects.update_or_create(user=request.user, defaults={'notifications_seen_at': timezone.now()})
    return JsonResponse({'unread': 0})
