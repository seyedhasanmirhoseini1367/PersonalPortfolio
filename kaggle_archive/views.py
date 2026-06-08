from django.views.generic import ListView, DetailView
from django.db.models import Q, Prefetch
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
        qs = Competition.objects.prefetch_related(
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
            Competition.objects
            .exclude(end_date__isnull=True)
            .dates('end_date', 'year', order='DESC')
        )
        ctx['total_competitions'] = Competition.objects.count()
        ctx['total_solutions']    = Solution.objects.count()
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

        ctx['top_solutions']        = solutions[:3]
        ctx['solutions']            = solutions
        ctx['technique_frequency']  = sorted(technique_counts.items(), key=lambda x: -x[1])
        ctx['related_competitions'] = Competition.objects.filter(
            competition_type=competition.competition_type
        ).exclude(id=competition.id)[:4]
        return ctx


# ── Admin manage views ────────────────────────────────────────────────────────

@staff_member_required
def manage_view(request):
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
    return render(request, 'kaggle_archive/manage.html', {
        'jobs':          jobs,
        'active_job_id': active_job_id,
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
