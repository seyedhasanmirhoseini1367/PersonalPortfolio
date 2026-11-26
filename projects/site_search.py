"""Top-bar search ("Search or ask AI") and the live chip next to it.

- search_api: /search/?q=... -> JSON results across projects, AI news,
  ML Explained walkthroughs and the Kaggle archive, for the Ctrl+K palette.
- live_chip: a context processor with one or two short "what's live" items
  (today's top AI news headline, the running Kaggle Playground episode).
  Cached for 10 minutes so it costs nothing per page.
"""
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

PER_GROUP = 4
POOL = 25   # candidates per group before ranking


def _rank(rows, q, title=lambda r: r.title):
    """Best first: a word in the title starts with the query, then the title contains it, then the rest."""
    import re
    word = re.compile(r'(?<![a-z0-9])' + re.escape(q.lower()))

    def score(r):
        t = (title(r) or '').lower()
        return 0 if word.search(t) else 1 if q.lower() in t else 2
    return sorted(rows, key=score)[:PER_GROUP]


def _projects(q):
    from .models import Projects
    qs = Projects.objects.filter(is_public=True).filter(
        Q(title__icontains=q) | Q(short_description__icontains=q) | Q(description__icontains=q))[:POOL]
    qs = _rank(qs, q)
    return [{'title': p.title, 'url': reverse('project_detail', args=[p.id]), 'icon': 'fas fa-cubes',
             'sub': p.get_project_type_display()} for p in qs]


def _news(q):
    from stories.models import DigestItem, Story
    out = []
    rows = DigestItem.objects.filter(Q(title__icontains=q) | Q(summary__icontains=q)).order_by('-digest_date')[:POOL]
    for it in _rank(rows, q):
        out.append({'title': it.title, 'icon': 'fas fa-bolt', 'sub': f'AI News · {it.digest_date:%d %b} · {it.source}',
                    'url': reverse('stories:story_detail', args=[f'ai-ml-digest-{it.digest_date.isoformat()}'])})
    if len(out) < PER_GROUP:
        stories = (Story.objects.filter(status=Story.Status.PUBLISHED, published_at__lte=timezone.now())
                   .exclude(slug__startswith='ai-ml-digest-')
                   .filter(Q(title__icontains=q) | Q(excerpt__icontains=q)).order_by('-published_at'))
        for s in stories[:PER_GROUP - len(out)]:
            out.append({'title': s.title, 'url': s.get_absolute_url(), 'icon': 'fas fa-newspaper', 'sub': 'AI News'})
    return out


def _walkthroughs(q):
    from model_internals.models import Walkthrough
    qs = Walkthrough.objects.filter(is_published=True).filter(
        Q(title__icontains=q) | Q(summary__icontains=q))[:POOL]
    qs = _rank(qs, q)
    return [{'title': w.title, 'url': w.get_absolute_url(), 'icon': 'fas fa-graduation-cap', 'sub': 'ML Explained'}
            for w in qs]


def _kaggle(q):
    from kaggle_archive.models import Competition
    qs = Competition.objects.filter(Q(name__icontains=q) | Q(slug__icontains=q)).order_by('-end_date')[:POOL]
    qs = _rank(qs, q, title=lambda c: c.name)
    out = []
    for c in qs:
        sub = (f'Playground S{c.season}E{c.episode}' if c.series == 'playground' and c.season and c.season > 2
               else 'Tabular Playground' if c.series == 'playground' else 'Kaggle competition')
        out.append({'title': c.name, 'url': c.get_absolute_url(), 'icon': 'fab fa-kaggle',
                    'sub': f'{sub}{f" · {c.end_date.year}" if c.end_date else ""}'})
    return out


def search_api(request):
    q = (request.GET.get('q') or '').strip()[:80]
    if len(q) < 2:
        return JsonResponse({'q': q, 'groups': []})
    groups = []
    for label, fn in (('Projects', _projects), ('AI News', _news), ('ML Explained', _walkthroughs),
                      ('Kaggle', _kaggle)):
        try:
            items = fn(q)
        except Exception:
            items = []
        if items:
            groups.append({'label': label, 'items': items})
    return JsonResponse({'q': q, 'groups': groups})


def _live_items():
    from kaggle_archive.models import Competition
    from stories.models import DigestItem, Story
    items = []
    today = timezone.localdate()
    digest = (Story.objects.filter(status=Story.Status.PUBLISHED, published_at__lte=timezone.now(),
                                   slug__startswith='ai-ml-digest-').order_by('-published_at').first())
    if digest:
        top = (DigestItem.objects.filter(digest_date=digest.slug[-10:]).exclude(summary='')
               .order_by('score', 'pk').first())
        items.append({'kind': 'news', 'label': 'Today in AI', 'text': top.title if top else digest.title,
                      'url': digest.get_absolute_url()})
    live = (Competition.objects.filter(series='playground', start_date__lte=today, end_date__gte=today)
            .order_by('-start_date').first())
    if live:
        days = (live.end_date - today).days
        code = f'S{live.season}E{live.episode}' if live.season and live.season > 2 else 'Playground'
        items.append({'kind': 'kaggle', 'label': f'Kaggle {code} live',
                      'text': f'{live.name} · {days} day{"" if days == 1 else "s"} left',
                      'url': reverse('kaggle_archive:playground')})
    return items


def live_chip(request):
    """Context processor: {'live_chip': [...]} for the top bar."""
    items = cache.get('live_chip_items')
    if items is None:
        try:
            items = _live_items()
        except Exception:
            items = []
        cache.set('live_chip_items', items, 600)
    return {'live_chip': items}
