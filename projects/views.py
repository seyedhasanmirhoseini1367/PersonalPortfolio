# projects/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
import json
import pandas as pd
import os
from .models import Projects, ProjectComment

# Auto-import all handlers so @register() decorators run at startup
import projects.inference.seizure_eeg          # noqa: F401
import projects.inference.image_classifier     # noqa: F401
import projects.inference.tabular_passthrough  # noqa: F401
import projects.inference.personality_predictor  # noqa: F401


# ──────────────────────────────────────────────────────────────────────────────
# List / detail / home
# ──────────────────────────────────────────────────────────────────────────────

def projects_list(request):
    project_type  = request.GET.get('type', '')
    skill_filter  = request.GET.get('skill', '')
    featured_only = request.GET.get('featured', '')

    projects = Projects.objects.filter(is_public=True)
    if project_type:   projects = projects.filter(project_type=project_type)
    if skill_filter:   projects = projects.filter(skills_used__contains=skill_filter)
    if featured_only:  projects = projects.filter(is_featured=True)

    context = {
        'projects': projects,
        'project_types': Projects.PROJECT_TYPE_CHOICES,
        'skills': Projects.SKILL_CHOICES,
        'active_type': project_type,
        'active_skill': skill_filter,
        'page_title': 'My Data Science Portfolio',
        'total_projects': projects.count(),
        'featured_count': projects.filter(is_featured=True).count(),
    }
    return render(request, 'projects/projects_list.html', context)


def project_detail(request, project_id):
    project = get_object_or_404(Projects, id=project_id, is_public=True)
    related_q = Q(project_type=project.project_type)
    for skill in project.get_skills_list():
        related_q |= Q(skills_used__contains=skill)
    related_projects = Projects.objects.filter(is_public=True).exclude(id=project_id).filter(related_q)[:3]

    comments = project.comments.filter(
        is_approved=True,
        parent__isnull=True,
    ).select_related('author').prefetch_related('replies__author').order_by('-created_at')

    return render(request, 'projects/project_detail.html', {
        'project': project,
        'kaggle_percentile': project.get_kaggle_percentile(),
        'skills_display':    project.get_skills_display(),
        'related_projects':  related_projects,
        'comments':          comments,
        'comment_count':     project.comments.filter(is_approved=True).count(),
    })


@require_POST
@login_required
def add_project_comment(request, project_id):
    project = get_object_or_404(Projects, id=project_id, is_public=True)
    content = request.POST.get('content', '').strip()
    parent_id = request.POST.get('parent_id', '').strip()

    if len(content) < 5:
        messages.error(request, 'Comment must be at least 5 characters.')
        return redirect('project_detail', project_id=project_id)

    parent = None
    if parent_id:
        parent = get_object_or_404(ProjectComment, id=parent_id, project=project)

    ProjectComment.objects.create(
        project=project,
        author=request.user,
        parent=parent,
        content=content,
        is_approved=True,
    )
    messages.success(request, 'Your comment has been posted!')
    return redirect('project_detail', project_id=project_id)


def home(request):
    skill_count = {}
    for p in Projects.objects.filter(is_public=True):
        for s in p.get_skills_list():
            skill_count[s] = skill_count.get(s, 0) + 1

    return render(request, 'projects/home.html', {
        'featured_projects': Projects.objects.filter(is_featured=True, is_public=True)[:6],
        'total_projects':    Projects.objects.filter(is_public=True).count(),
        'kaggle_projects':   Projects.objects.filter(project_type='KAGGLE_COMPETITION', is_public=True).count(),
        'top_skills':        sorted(skill_count.items(), key=lambda x: x[1], reverse=True)[:10],
        'skill_choices':     dict(Projects.SKILL_CHOICES),
    })


# ──────────────────────────────────────────────────────────────────────────────
# Prediction demo page
# ──────────────────────────────────────────────────────────────────────────────

def prediction_demo(request, project_id):
    project = get_object_or_404(Projects, id=project_id, is_public=True)
    if not project.has_prediction_capability():
        return render(request, 'projects/no_prediction.html', {'project': project})

    cfg = project.file_input_config or {}
    return render(request, 'projects/prediction_demo.html', {
        'project':          project,
        'file_input_config': cfg,
        'accepted_formats': cfg.get('accepted_formats', []),
        'demo_description': cfg.get('description', ''),
        'handler_slug':     cfg.get('handler', ''),
    })


# ──────────────────────────────────────────────────────────────────────────────
# File-based prediction  — single endpoint for ALL projects
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def file_prediction(request, project_id):
    """
    Universal file-upload prediction endpoint.

    All project-specific logic lives in the handler registered for
    project.file_input_config["handler"]. This view only orchestrates:
      1. Resolve handler
      2. Call handler.run(file)
      3. Return JSON

    Error handling is centralised: InferenceError → 400 with user message.
    Any other exception → 500 with generic message + server log.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    project = get_object_or_404(Projects, id=project_id, is_public=True)

    if not project.has_prediction_capability():
        return JsonResponse({
            'error': 'Demo not enabled for this project yet.'
        }, status=400)

    uploaded = request.FILES.get('signal_file')
    if not uploaded:
        return JsonResponse({
            'error': 'No file received. Please select a file and try again.'
        }, status=400)

    # Resolve handler
    try:
        from projects.inference import get_handler
        handler = get_handler(project)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    # Run inference
    try:
        from projects.inference.base import InferenceError
        result = handler.run(uploaded)
        return JsonResponse(result)

    except InferenceError as e:
        # User-facing validation error — show exactly as-is
        return JsonResponse({'error': str(e)}, status=400)

    except Exception as e:
        # Unexpected server error — log full traceback, return generic message
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'error': f'An unexpected error occurred during inference: {type(e).__name__}: {e}'
        }, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Manual prediction (kept for backward compat / simple projects)
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def make_prediction(request, project_id):
    """Manual form-field prediction (prediction_input_type = 'manual')."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    project = get_object_or_404(Projects, id=project_id, is_public=True)
    if not project.has_prediction_capability():
        return JsonResponse({'error': 'Prediction not enabled'}, status=400)

    try:
        import pickle
        input_data = {}
        for feature in project.input_features:
            value = request.POST.get(feature['name'])
            if value:
                input_data[feature['name']] = float(value) if feature.get('type') == 'number' else value
            else:
                input_data[feature['name']] = 0.0 if feature.get('type') == 'number' else ''

        path = project.get_model_path()
        if not path or not os.path.exists(path):
            return JsonResponse({'error': 'Model file not found'}, status=500)

        with open(path, 'rb') as f:
            model = pickle.load(f)

        df   = pd.DataFrame([input_data])
        pred = model.predict(df)
        return JsonResponse({'success': True, 'prediction': float(pred[0]), 'input_data': input_data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# RAG interpretation
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def interpret_prediction(request, project_id):
    """RAG-powered interpretation of a prediction result."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    project = get_object_or_404(Projects, id=project_id, is_public=True)
    try:
        body              = json.loads(request.body)
        prediction_result = body.get('prediction')
        prediction_label  = body.get('prediction_label', str(prediction_result))
        input_data        = body.get('input_data', {})

        if prediction_result is None:
            return JsonResponse({'error': 'prediction value is required'}, status=400)

        from rag_system.services.rag_service import RAGService
        result = RAGService().interpret_prediction(
            project=project,
            input_data=input_data,
            prediction_result=float(prediction_result),
            prediction_label=prediction_label,
        )
        return JsonResponse({
            'success':        result['success'],
            'interpretation': result['interpretation'],
            'sources':        result['sources'],
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ── Error handlers ────────────────────────────────────────────────────────────
def error_404(request, exception=None):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)
