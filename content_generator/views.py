import uuid
import json
import base64
import urllib.request
import urllib.error
import threading
import logging
from functools import wraps
from django.conf import settings
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import GenerationJob, CompanyProfile, ServiceProduct, CMSConnection, CompanyDocument


def client_required(view_func):
    """Allow access only to clients and staff (admins). Redirect unauthenticated users to login."""
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_staff or getattr(request.user, 'is_client', False):
            return view_func(request, *args, **kwargs)
        return render(request, 'content_generator/access_denied.html', status=403)
    return _wrapped

logger = logging.getLogger(__name__)

VARIANT_HINTS = [
    "",  # index 0 — no hint, base version
    "Make this version shorter and punchier than the base version. Cut every unnecessary word.",
    "Make this version story-driven with a narrative arc. Open with a relatable scenario.",
    "Make this version data-led. Lead with stats or a bold claim and back it up throughout.",
]


def _notify_slack(job):
    webhook_url = getattr(settings, 'SLACK_WEBHOOK_URL', '') or ''
    if not webhook_url:
        return
    try:
        status_icon = '✅' if job.status == GenerationJob.STATUS_DONE else '❌'
        score_text  = f'  •  Score: *{job.overall_score}/100*' if job.overall_score else ''
        text = (
            f"{status_icon} *{job.get_content_format_display()}* generation finished\n"
            f"Company: *{job.company_name}*{score_text}\n"
            f"<http://127.0.0.1:8000/ai-content-generator/group-result/{job.job_group_id}/|View result →>"
        )
        payload = json.dumps({'text': text}).encode()
        req = urllib.request.Request(
            webhook_url, data=payload,
            headers={'Content-Type': 'application/json'},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _user_profiles(user):
    """Profiles visible to a user: their own + admin-created global ones (owner=None)."""
    if user.is_staff:
        return CompanyProfile.objects.all()
    return CompanyProfile.objects.filter(Q(owner=user) | Q(owner__isnull=True))


def _owns_job(user, job):
    return user.is_staff or job.owner == user


@client_required
def demo_form(request):
    profile_id = request.GET.get('profile')
    service_id = request.GET.get('service')
    prefill    = {}

    if profile_id:
        profile = _user_profiles(request.user).filter(pk=profile_id).first()
        if profile:
            prefill['profile'] = profile
    if service_id:
        service = ServiceProduct.objects.filter(pk=service_id).first()
        if service:
            prefill['service'] = service
            if 'profile' not in prefill and _user_profiles(request.user).filter(pk=service.company_id).exists():
                prefill['profile'] = service.company
            prefill['keywords'] = service.name
            prefill['goal'] = f'Promote our {service.get_item_type_display().lower()}: {service.name}'

    return render(request, 'content_generator/form.html', {
        'profiles':       _user_profiles(request.user),
        'format_choices': GenerationJob.FORMAT_CHOICES,
        'tone_choices':   GenerationJob.TONE_CHOICES,
        'prefill':        prefill,
        'page_title':     'AI Content Generator',
    })


@client_required
@require_POST
def submit_job(request):
    formats       = request.POST.getlist('content_formats') or ['blog_post']
    tone_preset   = request.POST.get('tone_preset', 'professional')
    ab_variants   = max(1, min(3, int(request.POST.get('ab_variants', '1') or '1')))
    languages_raw = request.POST.getlist('target_languages') or ['English']
    target_languages = [l for l in languages_raw if l in ('English', 'Finnish')] or ['English']

    profile_id = request.POST.get('profile_id')
    service_id = request.POST.get('service_id')

    company_profile = CompanyProfile.objects.filter(pk=profile_id).first() if profile_id else None
    service         = ServiceProduct.objects.filter(pk=service_id).first() if service_id else None

    company_name    = (request.POST.get('company_name', '').strip()
                       or (company_profile.name if company_profile else ''))
    goal            = request.POST.get('goal', '').strip()
    keywords        = request.POST.get('keywords', '').strip()
    company_docs    = company_profile.about if company_profile else request.POST.get('company_docs', '').strip()
    competitor_docs = company_profile.competitor_info if company_profile else request.POST.get('competitor_docs', '').strip()

    group_id = uuid.uuid4()
    jobs = []

    for fmt in formats:
        variant_group = uuid.uuid4() if ab_variants > 1 else None
        for v_idx in range(ab_variants):
            job = GenerationJob.objects.create(
                job_group_id     = group_id,
                variant_group_id = variant_group,
                variant_index    = v_idx,
                owner            = request.user,
                company_profile  = company_profile,
                service          = service,
                company_name     = company_name,
                goal             = goal,
                content_format   = fmt,
                keywords         = keywords,
                company_docs     = company_docs,
                competitor_docs  = competitor_docs,
                tone_preset      = tone_preset,
                target_languages = target_languages,
                status           = GenerationJob.STATUS_PENDING,
            )
            jobs.append(job)
            threading.Thread(
                target=_run_pipeline,
                args=(str(job.id),),
                daemon=True,
            ).start()

    return render(request, 'content_generator/waiting.html', {
        'jobs':       jobs,
        'group_id':   group_id,
        'page_title': 'Generating Content…',
    })


@client_required
def group_status(request, group_id):
    jobs     = GenerationJob.objects.filter(job_group_id=group_id)
    statuses = list(jobs.values_list('status', flat=True))
    all_done = all(s in (GenerationJob.STATUS_DONE, GenerationJob.STATUS_FAILED) for s in statuses)
    return JsonResponse({
        'statuses':   statuses,
        'all_done':   all_done,
        'total':      len(statuses),
        'done_count': sum(1 for s in statuses if s in (GenerationJob.STATUS_DONE, GenerationJob.STATUS_FAILED)),
    })


@client_required
def content_history(request):
    jobs = (GenerationJob.objects
            .select_related('company_profile', 'service')
            .filter(owner=request.user, variant_index=0)
            .order_by('-created_at'))
    return render(request, 'content_generator/history.html', {
        'jobs':       jobs,
        'page_title': 'Content History',
    })


@client_required
def group_result(request, group_id):
    from django.http import Http404
    jobs = GenerationJob.objects.filter(job_group_id=group_id).order_by('content_format', 'variant_index')
    if not jobs.exists():
        raise Http404
    first = jobs.first()
    if not _owns_job(request.user, first):
        return render(request, 'content_generator/access_denied.html', status=403)
    cms_connections = []
    if first.company_profile_id:
        cms_connections = list(CMSConnection.objects.filter(
            company_profile_id=first.company_profile_id,
            is_active=True,
        ))
    return render(request, 'content_generator/result.html', {
        'jobs':            jobs,
        'group_id':        group_id,
        'cms_connections': cms_connections,
        'page_title':      'Generated Content',
    })


@client_required
@require_POST
def edit_job(request, job_id):
    job = get_object_or_404(GenerationJob, pk=job_id)
    if not _owns_job(request.user, job):
        return JsonResponse({'error': 'Not authorized'}, status=403)
    if not job.content_en:
        return JsonResponse({'error': 'No content to edit'}, status=400)
    data = json.loads(request.body)
    for field in ('title', 'headline', 'cta'):
        if field in data:
            job.content_en[field] = data[field]
    if 'sections' in data:
        job.content_en['sections'] = data['sections']
    job.save(update_fields=['content_en'])
    return JsonResponse({'status': 'saved'})


@client_required
@require_POST
def approve_job(request, job_id):
    job = get_object_or_404(GenerationJob, pk=job_id)
    if not _owns_job(request.user, job):
        return JsonResponse({'error': 'Not authorized'}, status=403)
    data = json.loads(request.body)
    approved = data.get('approved')  # True / False
    feedback = data.get('feedback', '').strip()
    job.user_approved = approved
    if feedback:
        job.user_feedback = feedback
    job.save(update_fields=['user_approved', 'user_feedback'])
    return JsonResponse({'status': 'saved', 'approved': approved})


@client_required
@require_POST
def rerun_job(request, job_id):
    original = get_object_or_404(GenerationJob, pk=job_id)
    if not _owns_job(request.user, original):
        return JsonResponse({'error': 'Not authorized'}, status=403)
    data     = json.loads(request.body)
    feedback = data.get('feedback', '').strip()

    new_group = uuid.uuid4()
    new_job   = GenerationJob.objects.create(
        job_group_id     = new_group,
        owner            = request.user,
        company_profile  = original.company_profile,
        service          = original.service,
        company_name     = original.company_name,
        goal             = original.goal,
        content_format   = original.content_format,
        keywords         = original.keywords,
        company_docs     = original.company_docs,
        competitor_docs  = original.competitor_docs,
        tone_preset      = original.tone_preset,
        target_languages = original.target_languages,
        parent_job       = original,
        user_feedback    = feedback,
        status           = GenerationJob.STATUS_PENDING,
    )
    threading.Thread(target=_run_pipeline, args=(str(new_job.id),), daemon=True).start()
    return JsonResponse({
        'status':    'started',
        'job_id':    str(new_job.id),
        'group_id':  str(new_group),
        'result_url': f'/ai-content-generator/group-result/{new_group}/',
    })


@client_required
@require_POST
def publish_cms(request, job_id):
    job = get_object_or_404(GenerationJob, pk=job_id)
    if not _owns_job(request.user, job):
        return JsonResponse({'error': 'Not authorized'}, status=403)
    if job.status != GenerationJob.STATUS_DONE or not job.content_en:
        return JsonResponse({'error': 'Job not complete'}, status=400)

    data        = json.loads(request.body)
    cms_type    = data.get('cms_type', 'wordpress')
    api_url     = data.get('api_url', '').rstrip('/')
    api_token   = data.get('api_token', '')
    cms_conn_id = data.get('cms_connection_id')

    if cms_conn_id:
        conn = CMSConnection.objects.filter(pk=cms_conn_id, is_active=True).first()
        if conn:
            cms_type  = conn.cms_type
            api_url   = conn.api_url.rstrip('/')
            api_token = conn.api_token

    if not api_url or not api_token:
        return JsonResponse({'error': 'Missing API URL or token'}, status=400)

    content = job.content_en
    title   = content.get('title', '')
    body_parts = []
    if content.get('headline'):
        body_parts.append(f"<h2>{content['headline']}</h2>")
    for sec in content.get('sections', []):
        if sec.get('heading'):
            body_parts.append(f"<h3>{sec['heading']}</h3>")
        if sec.get('body'):
            body_parts.append(f"<p>{sec['body']}</p>")
    if content.get('cta'):
        body_parts.append(f"<p><strong>{content['cta']}</strong></p>")
    html_body = "\n".join(body_parts)

    try:
        if cms_type == 'wordpress':
            result = _publish_wordpress(api_url, api_token, title, html_body,
                                        content.get('seo_description', ''))
        elif cms_type == 'notion':
            result = _publish_notion(api_url, api_token, title, content)
        else:
            return JsonResponse({'error': f'CMS type "{cms_type}" not yet supported'}, status=400)
        return JsonResponse({'status': 'published', 'url': result.get('url', '')})
    except Exception as exc:
        logger.exception("CMS publish failed for job %s", job_id)
        return JsonResponse({'error': str(exc)}, status=500)


def _publish_wordpress(api_url: str, app_password: str, title: str, html_body: str, excerpt: str):
    endpoint = f"{api_url}/wp-json/wp/v2/posts"
    payload  = json.dumps({
        'title':   {'raw': title},
        'content': {'raw': html_body},
        'excerpt': {'raw': excerpt},
        'status':  'draft',
    }).encode()
    creds    = base64.b64encode(app_password.encode()).decode()
    req      = urllib.request.Request(
        endpoint, data=payload,
        headers={
            'Content-Type':  'application/json',
            'Authorization': f'Basic {creds}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    return {'url': result.get('link', '')}


def _publish_notion(api_url: str, token: str, title: str, content: dict):
    # api_url is the parent page ID or database ID
    blocks = []
    if content.get('headline'):
        blocks.append({
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": content['headline']}}]},
        })
    for sec in content.get('sections', []):
        if sec.get('heading'):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": sec['heading']}}]},
            })
        if sec.get('body'):
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": sec['body']}}]},
            })
    payload = json.dumps({
        "parent": {"page_id": api_url},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "children": blocks,
    }).encode()
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages", data=payload,
        headers={
            'Content-Type':    'application/json',
            'Authorization':   f'Bearer {token}',
            'Notion-Version':  '2022-06-28',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    return {'url': result.get('url', '')}


def _run_pipeline(job_id: str):
    from .models import GenerationJob

    job = GenerationJob.objects.get(pk=job_id)
    job.status = GenerationJob.STATUS_RUNNING
    job.save(update_fields=['status'])

    try:
        from .pipeline.pipeline import run_pipeline

        keywords = [k.strip() for k in job.keywords.split(',') if k.strip()]

        # Build variant hint so A/B versions differ meaningfully
        variant_hint = VARIANT_HINTS[min(job.variant_index, len(VARIANT_HINTS) - 1)]
        feedback_with_hint = (
            (job.user_feedback + "\n\n" + variant_hint).strip()
            if job.user_feedback else variant_hint
        ) or None

        if job.company_profile_id:
            client_id            = f"company_{job.company_profile_id}"
            client_documents     = []
            profile              = job.company_profile
            structured_competitors = list(profile.competitors.values_list('description', flat=True))
            competitor_documents = structured_competitors or (
                [profile.competitor_info] if profile.competitor_info else []
            )
        else:
            client_id            = f"job_{job_id.replace('-', '')[:16]}"
            client_documents     = [job.company_docs]
            competitor_documents = [job.competitor_docs] if job.competitor_docs else []

        target_languages = job.target_languages or ['English']

        output = run_pipeline(
            client_id            = client_id,
            client_documents     = client_documents,
            competitor_documents = competitor_documents,
            goal                 = job.goal,
            target_languages     = target_languages,
            content_format       = job.content_format,
            keywords             = keywords,
            tone_preset          = job.tone_preset or 'professional',
            initial_feedback     = feedback_with_hint or None,
        )

        job.content_en    = output.content_en.model_dump() if output.content_en else None
        job.content_fi    = output.content_fi.model_dump() if output.content_fi else None
        job.evaluation    = output.evaluation.model_dump() if output.evaluation else None
        job.overall_score = output.evaluation.overall_score if output.evaluation else None
        job.status        = GenerationJob.STATUS_DONE

    except Exception as exc:
        logger.exception("Pipeline failed for job %s", job_id)
        job.status        = GenerationJob.STATUS_FAILED
        job.error_message = str(exc)

    job.save(update_fields=['status', 'content_en', 'content_fi', 'evaluation',
                             'overall_score', 'error_message'])
    _notify_slack(job)


# ── Company Profile CRUD (client-facing) ──────────────────────────────────────

@client_required
def profile_list(request):
    profiles = CompanyProfile.objects.filter(owner=request.user).prefetch_related('services')
    return render(request, 'content_generator/profile_list.html', {
        'profiles':   profiles,
        'page_title': 'My Company Profiles',
    })


def _profile_prefill(post=None, profile=None):
    """Build a plain dict of pre-fill values for profile_form.html."""
    src = post or {}
    return {
        'name':            src.get('name',            getattr(profile, 'name',            '') or ''),
        'about':           src.get('about',           getattr(profile, 'about',           '') or ''),
        'target_audience': src.get('target_audience', getattr(profile, 'target_audience', '') or ''),
        'tone_of_voice':   src.get('tone_of_voice',   getattr(profile, 'tone_of_voice',   '') or ''),
        'competitor_info': src.get('competitor_info', getattr(profile, 'competitor_info', '') or ''),
    }


@client_required
def profile_create(request):
    if request.method == 'POST':
        name            = request.POST.get('name', '').strip()
        about           = request.POST.get('about', '').strip()
        target_audience = request.POST.get('target_audience', '').strip()
        tone_of_voice   = request.POST.get('tone_of_voice', '').strip()
        competitor_info = request.POST.get('competitor_info', '').strip()
        if not name or not about:
            return render(request, 'content_generator/profile_form.html', {
                'error':   'Company name and description are required.',
                'prefill': _profile_prefill(post=request.POST),
                'is_edit': False,
                'page_title': 'New Company Profile',
            })
        profile = CompanyProfile.objects.create(
            owner=request.user, name=name, about=about,
            target_audience=target_audience, tone_of_voice=tone_of_voice,
            competitor_info=competitor_info,
        )
        from django.urls import reverse
        return redirect(reverse('content_generator:form') + f'?profile={profile.pk}')
    return render(request, 'content_generator/profile_form.html', {
        'prefill':    _profile_prefill(),
        'is_edit':    False,
        'page_title': 'New Company Profile',
    })


@client_required
def profile_edit(request, pk):
    profile = get_object_or_404(CompanyProfile, pk=pk)
    if not request.user.is_staff and profile.owner != request.user:
        return render(request, 'content_generator/access_denied.html', status=403)
    if request.method == 'POST':
        profile.name            = request.POST.get('name', profile.name).strip()
        profile.about           = request.POST.get('about', profile.about).strip()
        profile.target_audience = request.POST.get('target_audience', '').strip()
        profile.tone_of_voice   = request.POST.get('tone_of_voice', '').strip()
        profile.competitor_info = request.POST.get('competitor_info', '').strip()
        if not profile.name or not profile.about:
            return render(request, 'content_generator/profile_form.html', {
                'error':   'Company name and description are required.',
                'prefill': _profile_prefill(post=request.POST),
                'is_edit': True,
                'page_title': f'Edit — {profile.name}',
            })
        profile.save()
        return redirect('content_generator:profile_list')
    return render(request, 'content_generator/profile_form.html', {
        'prefill':    _profile_prefill(profile=profile),
        'is_edit':    True,
        'page_title': f'Edit — {profile.name}',
    })


@client_required
@require_POST
def profile_delete(request, pk):
    profile = get_object_or_404(CompanyProfile, pk=pk)
    if not request.user.is_staff and profile.owner != request.user:
        return JsonResponse({'error': 'Not authorized'}, status=403)
    profile.delete()
    return redirect('content_generator:profile_list')


# ── Client Workspace ──────────────────────────────────────────────────────────

def _get_or_create_workspace_profile(user):
    """Return the client's owned company profile, creating a blank one if needed."""
    profile = CompanyProfile.objects.filter(owner=user).first()
    if not profile:
        profile = CompanyProfile.objects.create(
            owner=user,
            name=user.get_full_name() or user.username,
            about='',
        )
    return profile


@client_required
def workspace(request):
    profile  = _get_or_create_workspace_profile(request.user)
    services  = profile.services.all().order_by('display_order', 'name')
    documents = profile.documents.all()
    recent_jobs = (GenerationJob.objects
                   .filter(owner=request.user, status=GenerationJob.STATUS_DONE)
                   .select_related('service', 'company_profile')
                   .order_by('-created_at')[:6])
    return render(request, 'content_generator/workspace.html', {
        'profile':        profile,
        'services':       services,
        'documents':      documents,
        'recent_jobs':    recent_jobs,
        'format_choices': GenerationJob.FORMAT_CHOICES,
        'page_title':     'My Workspace',
    })


@client_required
@require_POST
def document_upload(request):
    profile = _get_or_create_workspace_profile(request.user)
    f = request.FILES.get('file')
    if not f:
        return redirect('content_generator:workspace')
    title = request.POST.get('title', '').strip() or f.name
    CompanyDocument.objects.create(company_profile=profile, title=title, file=f)
    return redirect('content_generator:workspace')


@client_required
@require_POST
def document_delete(request, pk):
    doc = get_object_or_404(CompanyDocument, pk=pk)
    if not request.user.is_staff and doc.company_profile.owner != request.user:
        return JsonResponse({'error': 'Not authorized'}, status=403)
    doc.file.delete(save=False)
    doc.delete()
    return redirect('content_generator:workspace')


@client_required
def workspace_profile_edit(request):
    """Edit the client's own company profile from the workspace."""
    profile = _get_or_create_workspace_profile(request.user)
    if request.method == 'POST':
        profile.name            = request.POST.get('name', profile.name).strip() or profile.name
        profile.about           = request.POST.get('about', '').strip()
        profile.target_audience = request.POST.get('target_audience', '').strip()
        profile.tone_of_voice   = request.POST.get('tone_of_voice', '').strip()
        profile.competitor_info = request.POST.get('competitor_info', '').strip()
        if not profile.about:
            return render(request, 'content_generator/workspace_profile_edit.html', {
                'profile': profile,
                'error':   'Company description is required.',
                'page_title': 'Edit Company Info',
            })
        profile.save()
        return redirect('content_generator:workspace')
    return render(request, 'content_generator/workspace_profile_edit.html', {
        'profile':    profile,
        'page_title': 'Edit Company Info',
    })


# ── Service / Product CRUD ────────────────────────────────────────────────────

def _service_prefill(post=None, service=None):
    src = post or {}
    return {
        'name':        src.get('name',        getattr(service, 'name',        '') or ''),
        'description': src.get('description', getattr(service, 'description', '') or ''),
        'item_type':   src.get('item_type',   getattr(service, 'item_type',   ServiceProduct.TYPE_SERVICE)),
        'video_url':   src.get('video_url',   getattr(service, 'video_url',   '') or ''),
    }


@client_required
def service_create(request):
    profile = _get_or_create_workspace_profile(request.user)
    if request.method == 'POST':
        name        = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        item_type   = request.POST.get('item_type', ServiceProduct.TYPE_SERVICE)
        video_url   = request.POST.get('video_url', '').strip()
        if not name or not description:
            return render(request, 'content_generator/service_form.html', {
                'prefill':    _service_prefill(post=request.POST),
                'is_edit':    False,
                'error':      'Name and description are required.',
                'page_title': 'Add Service / Product',
            })
        svc = ServiceProduct(
            company=profile, name=name,
            description=description, item_type=item_type,
            video_url=video_url or None,
        )
        if request.FILES.get('image'):
            svc.image = request.FILES['image']
        if request.FILES.get('document'):
            svc.document = request.FILES['document']
        svc.save()
        return redirect('content_generator:workspace')
    return render(request, 'content_generator/service_form.html', {
        'prefill':    _service_prefill(),
        'is_edit':    False,
        'page_title': 'Add Service / Product',
    })


@client_required
def service_edit(request, pk):
    service = get_object_or_404(ServiceProduct, pk=pk)
    if not request.user.is_staff and service.company.owner != request.user:
        return render(request, 'content_generator/access_denied.html', status=403)
    if request.method == 'POST':
        name        = request.POST.get('name', service.name).strip()
        description = request.POST.get('description', '').strip()
        item_type   = request.POST.get('item_type', service.item_type)
        video_url   = request.POST.get('video_url', '').strip()
        if not name or not description:
            return render(request, 'content_generator/service_form.html', {
                'prefill':    _service_prefill(post=request.POST),
                'service':    service,
                'is_edit':    True,
                'error':      'Name and description are required.',
                'page_title': f'Edit — {service.name}',
            })
        service.name        = name
        service.description = description
        service.item_type   = item_type
        service.video_url   = video_url or None
        if request.FILES.get('image'):
            if service.image:
                service.image.delete(save=False)
            service.image = request.FILES['image']
        if request.FILES.get('document'):
            if service.document:
                service.document.delete(save=False)
            service.document = request.FILES['document']
        service.save()
        return redirect('content_generator:workspace')
    return render(request, 'content_generator/service_form.html', {
        'prefill':    _service_prefill(service=service),
        'service':    service,
        'is_edit':    True,
        'page_title': f'Edit — {service.name}',
    })


@client_required
@require_POST
def service_delete(request, pk):
    service = get_object_or_404(ServiceProduct, pk=pk)
    if not request.user.is_staff and service.company.owner != request.user:
        return JsonResponse({'error': 'Not authorized'}, status=403)
    service.delete()
    return redirect('content_generator:workspace')
