from django.conf import settings
from django.utils import timezone
from django.views.generic import ListView, DetailView
from django.db.models import Q, Prefetch, Count
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Competition, Solution, Technique, ExtractionJob


class CompetitionListView(ListView):
    model            = Competition
    template_name    = 'kaggle_archive/competition_list.html'
    context_object_name = 'competitions'
    paginate_by      = 12

    def get_queryset(self):
        top3_qs = Solution.objects.filter(rank__lte=3).prefetch_related('techniques').order_by('rank')
        # Featured / Research only; the monthly Playground Series has its own calendar page.
        qs = Competition.objects.exclude(series=Competition.SERIES_PLAYGROUND).prefetch_related(
            Prefetch('solutions', queryset=top3_qs)
        )

        q         = self.request.GET.get('q', '').strip()
        type_     = self.request.GET.get('type', '').strip()
        domain    = self.request.GET.get('domain', '').strip()
        year      = self.request.GET.get('year', '').strip()
        technique = self.request.GET.get('technique', '').strip()
        sort      = self.request.GET.get('sort', '-end_date').strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(host__icontains=q) |
                Q(solutions__team_name__icontains=q) |
                Q(solutions__techniques__name__icontains=q)
            ).distinct()

        if type_:
            qs = qs.filter(competition_type=type_)

        if domain:
            qs = qs.filter(domain=domain)

        if year:
            qs = qs.filter(end_date__year=year)

        if technique:
            qs = qs.filter(solutions__techniques__slug=technique).distinct()

        sort_map = {
            '-end_date':  '-end_date',
            'end_date':   'end_date',
            '-num_teams': '-num_teams',
            'num_teams':  'num_teams',
        }
        return qs.order_by(sort_map.get(sort, '-end_date'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['competition_types'] = Competition.TYPE_CHOICES
        ctx['domains']           = Competition.DOMAIN_CHOICES
        ctx['techniques']        = Technique.objects.all().order_by('name')
        ctx['years']             = (
            Competition.objects.exclude(series=Competition.SERIES_PLAYGROUND)
            .exclude(end_date__isnull=True)
            .dates('end_date', 'year', order='DESC')
        )
        featured = Competition.objects.exclude(series=Competition.SERIES_PLAYGROUND)
        ctx['total_competitions'] = featured.count()
        ctx['total_solutions']    = Solution.objects.filter(competition__in=featured).count()
        ctx['playground_count']   = Competition.objects.filter(series=Competition.SERIES_PLAYGROUND).count()
        ctx['tab'] = 'featured'
        ctx['total_techniques']   = Technique.objects.count()
        ctx['current_filters'] = {
            'q':         self.request.GET.get('q', ''),
            'type':      self.request.GET.get('type', ''),
            'domain':    self.request.GET.get('domain', ''),
            'year':      self.request.GET.get('year', ''),
            'technique': self.request.GET.get('technique', ''),
            'sort':      self.request.GET.get('sort', '-end_date'),
        }
        return ctx


class CompetitionDetailView(DetailView):
    model               = Competition
    template_name       = 'kaggle_archive/competition_detail.html'
    context_object_name = 'competition'

    def get_queryset(self):
        return Competition.objects.prefetch_related(
            Prefetch('solutions',
                     queryset=Solution.objects.prefetch_related('techniques').order_by('rank'))
        )

    def get_context_data(self, **kwargs):
        ctx         = super().get_context_data(**kwargs)
        competition = ctx['competition']
        solutions   = list(competition.solutions.all())

        technique_counts = {}
        for sol in solutions:
            for tech in sol.techniques.all():
                technique_counts[tech.name] = technique_counts.get(tech.name, 0) + 1

        # Learning cards, prepared for the template (fixed section order).
        from .summarizer import CARD_SECTIONS
        compare_columns = [('validation', 'Validation'), ('models', 'Models'),
                           ('ensembling', 'Ensembling & post-processing'),
                           ('didnt_work', "Didn't work")]
        cards = []
        for sol in solutions:
            if not sol.card:
                continue
            cards.append({
                'solution': sol,
                'headline': sol.card.get('headline', ''),
                'sections': [(label, sol.card.get(key) or []) for key, label, _ in CARD_SECTIONS
                             if sol.card.get(key)],
                'cells': [sol.card.get(key) or [] for key, _ in compare_columns],
            })
        ctx['cards']    = cards
        ctx['insights'] = competition.insights or {}
        learned = set()
        if self.request.user.is_authenticated:
            from .models import LearnedLesson
            learned = set(LearnedLesson.objects.filter(user=self.request.user, competition=competition)
                          .values_list('lesson_key', flat=True))
        ctx['lessons'] = [{'text': t, 'learned': lesson_key(t) in learned}
                          for t in (competition.insights or {}).get('lessons', [])]
        ctx['compare_columns'] = [label for _, label in compare_columns]
        ctx['without_writeup'] = [s for s in solutions if not s.card]

        ctx['top_solutions']        = solutions[:3]
        ctx['solutions']            = solutions
        ctx['technique_frequency']  = sorted(technique_counts.items(), key=lambda x: -x[1])
        if competition.series == Competition.SERIES_PLAYGROUND:
            ctx['related_competitions'] = Competition.objects.filter(
                series=Competition.SERIES_PLAYGROUND, season=competition.season
            ).exclude(id=competition.id).order_by('-episode')[:4]
        else:
            ctx['related_competitions'] = Competition.objects.filter(
                competition_type=competition.competition_type
            ).exclude(series=Competition.SERIES_PLAYGROUND).exclude(id=competition.id)[:4]
        return ctx


# ── Admin manage views ────────────────────────────────────────────────────────

@staff_member_required
def manage_view(request):
    from . import auto
    from .models import KaggleSyncItem, KaggleSyncRun
    if request.method == 'POST' and request.POST.get('action') == 'sync':
        if auto.enabled():
            import threading
            threading.Thread(target=auto.run_sync, args=('manual',), daemon=True).start()
        return redirect(request.path)
    if request.method == 'POST':
        url   = request.POST.get('url', '').strip()
        top_n = int(request.POST.get('top_n', 10))
        if url:
            from .extractor import run_job_in_background
            job = ExtractionJob.objects.create(url=url, top_n=top_n)
            run_job_in_background(job.id)
            return redirect(f'{request.path}?job={job.id}')

    active_job_id = request.GET.get('job')
    jobs          = ExtractionJob.objects.select_related('competition')[:30]
    last_done = KaggleSyncRun.objects.filter(status='done').first()
    days_left = 0
    if last_done:
        days_left = max(0, (last_done.started_at + auto.RUN_EVERY - timezone.now()).days)
    return render(request, 'kaggle_archive/manage.html', {
        'jobs':             jobs,
        'active_job_id':    active_job_id,
        'sync_enabled':     auto.enabled(),
        'sync_limit':       getattr(settings, 'KAGGLE_AUTO_SYNC_LIMIT', 3),
        'sync_runs':        KaggleSyncRun.objects.all()[:5],
        'sync_items':       KaggleSyncItem.objects.all()[:60],
        'next_run_due':     auto.enabled() and auto.is_due(),
        'next_run_in_days': days_left,
    })


@staff_member_required
def job_status_view(request, job_id):
    job  = get_object_or_404(ExtractionJob, id=job_id)
    data = {
        'status':           job.status,
        'log':              job.log,
        'solutions_saved':  job.solutions_saved,
        'duration':         job.duration(),
        'competition_slug': job.competition.slug if job.competition else '',
        'competition_name': job.competition.name if job.competition else '',
    }
    return JsonResponse(data)


# ── Trends & learning progress ───────────────────────────────────────────────

def lesson_key(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or '').strip().encode('utf-8')).hexdigest()


def trends_view(request):
    """What top teams used, per competition type, plus every lesson in one place."""
    from collections import Counter
    from .models import LearnedLesson

    learned = set()
    if request.user.is_authenticated:
        learned = set(LearnedLesson.objects.filter(user=request.user)
                      .values_list('competition_id', 'lesson_key'))

    groups = []
    comps = (Competition.objects.exclude(series=Competition.SERIES_PLAYGROUND)
             .prefetch_related('solutions__techniques').order_by('-end_date', 'name'))
    by_type = {}
    for comp in comps:
        by_type.setdefault(comp.competition_type, []).append(comp)
    labels = dict(Competition.TYPE_CHOICES)
    total_lessons = done_lessons = 0
    for type_, items in by_type.items():
        teams = 0
        tech = Counter()
        for comp in items:
            for sol in comp.solutions.all():
                teams += 1
                tech.update({t.name for t in sol.techniques.all()})
        lessons, baseline = [], []
        for comp in items:
            ins = comp.insights or {}
            for text in ins.get('lessons', []):
                key = lesson_key(text)
                is_done = (comp.id, key) in learned
                lessons.append({'text': text, 'competition': comp, 'key': key, 'learned': is_done})
                total_lessons += 1
                done_lessons += is_done
            for c in ins.get('common', []):
                baseline.append({'idea': c.get('idea', ''), 'competition': comp})
        groups.append({
            'type': type_, 'label': labels.get(type_, type_.title()),
            'competitions': items, 'teams': teams,
            'techniques': [{'name': n, 'count': c, 'pct': round(100 * c / teams) if teams else 0}
                           for n, c in tech.most_common(10)],
            'lessons': lessons, 'baseline': baseline[:8],
        })
    groups.sort(key=lambda g: -len(g['competitions']))
    return render(request, 'kaggle_archive/trends.html', {
        'tab': 'trends',
        'playground_count': Competition.objects.filter(series=Competition.SERIES_PLAYGROUND).count(),
        'groups': groups,
        'total_lessons': total_lessons,
        'done_lessons': done_lessons,
    })


@require_POST
def toggle_lesson(request, slug):
    """Mark / unmark a lesson as learned (signed-in users)."""
    import json
    from .models import LearnedLesson
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Log in to track what you learned.'}, status=401)
    comp = get_object_or_404(Competition, slug=slug)
    try:
        text = json.loads(request.body or b'{}').get('lesson', '')
    except (ValueError, AttributeError):
        text = ''
    key = lesson_key(text)
    if key not in {lesson_key(t) for t in (comp.insights or {}).get('lessons', [])}:
        return JsonResponse({'error': 'Unknown lesson.'}, status=400)
    obj, created = LearnedLesson.objects.get_or_create(user=request.user, competition=comp, lesson_key=key)
    if not created:
        obj.delete()
    return JsonResponse({'learned': created})


# ── Playground Series: a 12-month calendar per year ─────────────────────────

MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def playground_view(request):
    from .models import PlaygroundYear
    today = timezone.localdate()
    episodes = list(Competition.objects.filter(series=Competition.SERIES_PLAYGROUND)
                    .annotate(n_solutions=Count('solutions', distinct=True),
                              n_writeups=Count('solutions', filter=~Q(solutions__writeup_content=''), distinct=True))
                    .order_by('start_date', 'episode'))

    from .playground import calendar_month as month_of

    years = sorted({month_of(c)[0] for c in episodes if month_of(c)[0]}, reverse=True)
    try:
        year = int(request.GET.get('year') or 0)
    except ValueError:
        year = 0
    if year not in years:
        year = years[0] if years else today.year

    def state(c):
        if c.start_date and c.end_date and c.start_date <= today <= c.end_date:
            return 'live'
        if c.start_date and c.start_date > today:
            return 'upcoming'
        if c.analyzed_at:
            return 'analysed'
        return 'pending'

    months = [{'num': i + 1, 'name': n, 'episodes': []} for i, n in enumerate(MONTH_NAMES)]
    season = None
    for c in episodes:
        y, m = month_of(c)
        if y == year:
            c.state = state(c)
            c.days_left = (c.end_date - today).days if c.state == 'live' else None
            months[m - 1]['episodes'].append(c)
            season = season or c.season
    for m in months:
        m['future'] = not m['episodes'] and (year > today.year or (year == today.year and m['num'] > today.month))

    live = next((c for c in reversed(episodes) if state(c) == 'live'), None)
    if live:
        live.days_left = (live.end_date - today).days
    in_year = [c for m in months for c in m['episodes']]
    return render(request, 'kaggle_archive/playground.html', {
        'tab': 'playground',
        'years': years, 'year': year, 'season': season, 'months': months,
        'year_summary': PlaygroundYear.objects.filter(season=season).first() if season else None,
        'year_total': len(in_year),
        'year_analysed': sum(1 for c in in_year if c.analyzed_at),
        'live': live,
        'total_episodes': len(episodes),
        'total_analysed': sum(1 for c in episodes if c.analyzed_at),
        'first_year': min(years) if years else None,
        'task_counts': {t: sum(1 for c in in_year if c.task == t) for t in ('classification', 'regression', 'other')},
    })
