# projects/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
import io
import json
import pandas as pd
import os
from .models import Projects, ProjectComment
from stories.models import Story

# Auto-import all handlers so @register() decorators run at startup
import projects.inference.seizure_eeg          # noqa: F401
import projects.inference.image_classifier     # noqa: F401
import projects.inference.tabular_passthrough  # noqa: F401
import projects.inference.personality_predictor  # noqa: F401
import projects.inference.irrigation_predictor   # noqa: F401
import projects.inference.eeg_foundation         # noqa: F401


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
        'page_title': 'ML Models',
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
    from django.contrib.auth import get_user_model
    from resume.models import ResumeSetting
    User = get_user_model()

    skill_count = {}
    for p in Projects.objects.filter(is_public=True):
        for s in p.get_skills_list():
            skill_count[s] = skill_count.get(s, 0) + 1

    portfolio_owner = User.objects.filter(is_superuser=True).first()
    resume_setting = ResumeSetting.objects.prefetch_related('quick_facts').first()

    return render(request, 'home.html', {
        'featured_projects': Projects.objects.filter(is_featured=True, is_public=True)[:6],
        'total_projects':    Projects.objects.filter(is_public=True).count(),
        'kaggle_projects':   Projects.objects.filter(project_type='KAGGLE_COMPETITION', is_public=True).count(),
        'top_skills':        sorted(skill_count.items(), key=lambda x: x[1], reverse=True)[:10],
        'skill_choices':     dict(Projects.SKILL_CHOICES),
        'latest_stories':    Story.objects.filter(status=Story.Status.PUBLISHED).order_by('-published_at')[:4],
        'portfolio_owner':   portfolio_owner,
        'resume_setting':    resume_setting,
        'quick_facts':       resume_setting.quick_facts.all() if resume_setting else [],
    })


# ──────────────────────────────────────────────────────────────────────────────
# Prediction demo page
# ──────────────────────────────────────────────────────────────────────────────

def prediction_demo(request, project_id):
    project = get_object_or_404(Projects, id=project_id, is_public=True)
    if not project.has_prediction_capability():
        return render(request, 'projects/no_prediction.html', {'project': project})

    cfg = project.file_input_config or {}

    # Check if the handler supports sample-data demo
    has_sample_demo = False
    try:
        from projects.inference import get_handler
        handler = get_handler(project)
        has_sample_demo = hasattr(handler, 'run_sample')
    except Exception:
        pass

    return render(request, 'projects/prediction_demo.html', {
        'project':               project,
        'file_input_config':     cfg,
        'accepted_formats':      cfg.get('accepted_formats', []),
        'demo_description':      cfg.get('description', ''),
        'handler_slug':          cfg.get('handler', ''),
        'input_features':        project.input_features or [],
        'prediction_input_type': project.prediction_input_type,
        'has_sample_demo':       has_sample_demo,
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
    import time
    from monitoring.utils import log_prediction
    try:
        from projects.inference.base import InferenceError
        t0     = time.perf_counter()
        result = handler.run(uploaded)
        ms     = int((time.perf_counter() - t0) * 1000)

        log_prediction(
            project=project, user=request.user, input_type='file',
            prediction=result.get('prediction'), confidence=result.get('confidence'),
            label=str(result.get('label', '')), inference_ms=ms,
            success=True, source='web', request=request,
        )
        from monitoring.notifications import check_milestone
        check_milestone(project)
        return JsonResponse(result)

    except InferenceError as e:
        log_prediction(project=project, user=request.user, input_type='file',
                       success=False, error_message=str(e), source='web', request=request)
        return JsonResponse({'error': str(e)}, status=400)

    except Exception as e:
        import traceback
        traceback.print_exc()
        log_prediction(project=project, user=request.user, input_type='file',
                       success=False, error_message=str(e), source='web', request=request)
        return JsonResponse({
            'error': f'An unexpected error occurred during inference: {type(e).__name__}: {e}'
        }, status=500)


# ──────────────────────────────────────────────────────────────────────────────
# Sample-data prediction — runs handler.run_sample() (no file upload needed)
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
def sample_prediction(request, project_id):
    """
    POST /project/<id>/sample-prediction/
    Runs inference on the pre-saved sample EEG window.
    The handler must implement run_sample(); raises InferenceError otherwise.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    project = get_object_or_404(Projects, id=project_id, is_public=True)
    if not project.has_prediction_capability():
        return JsonResponse({'error': 'Demo not enabled for this project.'}, status=400)

    try:
        from projects.inference import get_handler
        handler = get_handler(project)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not hasattr(handler, 'run_sample'):
        return JsonResponse({'error': 'This project does not support sample-data demo.'}, status=400)

    import time
    from monitoring.utils import log_prediction
    try:
        from projects.inference.base import InferenceError
        t0     = time.perf_counter()
        result = handler.run_sample()
        ms     = int((time.perf_counter() - t0) * 1000)
        log_prediction(
            project=project, user=request.user, input_type='file',
            prediction=result.get('prediction'), confidence=result.get('confidence'),
            label=str(result.get('prediction_label', '')), inference_ms=ms,
            success=True, source='web_sample', request=request,
        )
        return JsonResponse(result)
    except InferenceError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'{type(e).__name__}: {e}'}, status=500)


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

        from rag_system.services.generation_service import GenerationService
        gen = GenerationService()
        label_str = prediction_label or str(prediction_result)
        interpretation = gen.generate_prediction_interpretation(
            project_title=project.title,
            project_description=project.description,
            model_type=project.get_model_type_display() if project.model_type else 'ML Model',
            target_feature=project.target_feature,
            input_data=input_data,
            prediction_result=float(prediction_result),
            prediction_label=label_str,
            context_chunks=[],
        )
        result = {'success': True, 'interpretation': interpretation, 'sources': []}
        return JsonResponse({
            'success':        result['success'],
            'interpretation': result['interpretation'],
            'sources':        result['sources'],
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    except BaseException as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'[{type(e).__name__}] {e}'}, status=500)


@csrf_exempt
def interpret_ensemble(request):
    """Build an ensemble-aware interpretation across all seizure model results."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        body           = json.loads(request.body)
        ensemble_label = body.get('ensemble_label', '')
        ensemble_votes = body.get('ensemble_votes', {})
        models_data    = body.get('models_data', [])

        if not ensemble_label:
            return JsonResponse({'error': 'ensemble_label is required'}, status=400)

        from rag_system.services.generation_service import GenerationService
        gen = GenerationService()
        interpretation = gen.generate_ensemble_interpretation(
            ensemble_label=ensemble_label,
            ensemble_votes=ensemble_votes,
            models_data=models_data,
        )
        return JsonResponse({'success': True, 'interpretation': interpretation})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)
    except BaseException as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'[{type(e).__name__}] {e}'}, status=500)


def seizure_comparison_view(request):
    """GET: Side-by-side comparison of all three seizure EEG models."""
    seizure_projects = [
        p for p in Projects.objects.filter(is_public=True)
        if (p.file_input_config or {}).get('handler') == 'seizure_eeg'
    ]
    return render(request, 'projects/seizure_comparison.html', {
        'seizure_projects': seizure_projects,
        'page_title':       'Seizure Detection — Model Comparison',
    })


@csrf_exempt
def seizure_comparison_predict(request):
    """POST: Run all seizure_eeg models on the uploaded file; return JSON with all results."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    uploaded = request.FILES.get('signal_file')
    if not uploaded:
        return JsonResponse({'error': 'No file received. Please select a file and try again.'}, status=400)

    if not uploaded.name.lower().endswith('.parquet'):
        return JsonResponse(
            {'error': f'Only .parquet files are accepted. You uploaded "{uploaded.name}".'},
            status=400,
        )

    seizure_projects = [
        p for p in Projects.objects.filter(is_public=True)
        if (p.file_input_config or {}).get('handler') == 'seizure_eeg'
    ]
    if not seizure_projects:
        return JsonResponse({'error': 'No seizure detection models are configured.'}, status=404)

    file_bytes = uploaded.read()
    filename   = uploaded.name

    from projects.inference import get_handler
    from projects.inference.base import InferenceError
    from monitoring.utils import log_prediction
    import time

    results = []
    for project in seizure_projects:
        file_obj      = io.BytesIO(file_bytes)
        file_obj.name = filename
        variant       = (project.file_input_config or {}).get('model_variant', 'unknown')

        try:
            handler = get_handler(project)
            t0      = time.perf_counter()
            result  = handler.run(file_obj)
            ms      = int((time.perf_counter() - t0) * 1000)

            try:
                log_prediction(
                    project=project, user=request.user, input_type='file',
                    prediction=result.get('prediction'),
                    confidence=result.get('prediction_proba'),
                    label=str(result.get('prediction_label', '')),
                    inference_ms=ms, success=True,
                    source='web_comparison', request=request,
                )
            except Exception:
                pass

            results.append({
                'project_id':       project.id,
                'project_title':    project.title,
                'model_variant':    variant,
                'success':          True,
                'prediction':       result.get('prediction'),
                'prediction_label': result.get('prediction_label'),
                'confidence':       result.get('prediction_proba'),
                'inference_ms':     ms,
                'input_summary':    result.get('input_summary', {}),
                'input_data':       result.get('input_data', {}),
            })

        except InferenceError as e:
            log_prediction(project=project, user=request.user, input_type='file',
                           success=False, error_message=str(e),
                           source='web_comparison', request=request)
            results.append({
                'project_id':    project.id,
                'project_title': project.title,
                'model_variant': variant,
                'success':       False,
                'error':         str(e),
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            log_prediction(project=project, user=request.user, input_type='file',
                           success=False, error_message=str(e),
                           source='web_comparison', request=request)
            results.append({
                'project_id':    project.id,
                'project_title': project.title,
                'model_variant': variant,
                'success':       False,
                'error':         f'{type(e).__name__}: {e}',
            })

    # Majority-vote ensemble over successful predictions
    labels = [r['prediction_label'] for r in results if r.get('success') and r.get('prediction_label')]
    ensemble_label = None
    ensemble_votes = {}
    if labels:
        ensemble_votes = {lbl: labels.count(lbl) for lbl in set(labels)}
        ensemble_label = max(ensemble_votes, key=ensemble_votes.get)

    return JsonResponse({
        'success':        True,
        'results':        results,
        'ensemble_label': ensemble_label,
        'ensemble_votes': ensemble_votes,
    })


def roadmap(request):
    """MLOps learning roadmap page."""
    return render(request, 'projects/roadmap.html')


# ── Real-time EEG Seizure Detection — DEV / TEST only ─────────────────────────

def seizure_realtime_view(request):
    return render(request, 'projects/seizure_realtime.html')


@csrf_exempt
@require_POST
def seizure_realtime_load(request):
    """
    Accept 1–10 .parquet/.csv EEG files (multipart field name "files"),
    concatenate them row-wise, and return the combined signal as JSON.
    All files must share the same column set.
    Dev-only — no auth, no logging.
    """
    MAX_FILES = 10
    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'error': 'No files uploaded.'}, status=400)
    if len(files) > MAX_FILES:
        return JsonResponse({'error': f'Maximum {MAX_FILES} files allowed.'}, status=400)

    frames = []
    file_meta = []
    ref_columns = None

    for f in files:
        name = f.name.lower()
        if not (name.endswith('.parquet') or name.endswith('.csv')):
            return JsonResponse(
                {'error': f'"{f.name}" is not a .parquet or .csv file.'},
                status=400,
            )
        try:
            if name.endswith('.parquet'):
                df_i = pd.read_parquet(io.BytesIO(f.read()))
            else:
                df_i = pd.read_csv(f)
        except Exception as e:
            return JsonResponse({'error': f'Could not read "{f.name}": {e}'}, status=400)

        if 'EKG' in df_i.columns:
            df_i = df_i.drop(columns=['EKG'])

        cols_i = list(df_i.columns[:19])
        df_i = df_i[cols_i]

        if ref_columns is None:
            ref_columns = cols_i
        elif cols_i != ref_columns:
            return JsonResponse(
                {'error': f'Column mismatch in "{f.name}". '
                          f'Expected {ref_columns}, got {cols_i}.'},
                status=400,
            )

        file_meta.append({'name': f.name, 'samples': len(df_i)})
        frames.append(df_i)

    df = pd.concat(frames, ignore_index=True)
    columns = ref_columns
    total_samples = len(df)

    if total_samples < 256:
        return JsonResponse({'error': f'Combined signal too short ({total_samples} samples).'}, status=400)

    data = {col: df[col].astype('float32').round(6).tolist() for col in columns}

    return JsonResponse({
        'columns':       columns,
        'total_samples': total_samples,
        'sampling_rate': 200,
        'duration_sec':  round(total_samples / 200, 1),
        'file_count':    len(files),
        'files':         file_meta,
        'data':          data,
    })


def seizure_realtime_models(request):
    """GET: Return list of available seizure_eeg model variants from the database."""
    seizure_projects = [
        p for p in Projects.objects.filter(is_public=True)
        if (p.file_input_config or {}).get('handler') == 'seizure_eeg'
    ]
    models = [
        {
            'variant': (p.file_input_config or {}).get('model_variant', 'unknown'),
            'title':   p.title,
        }
        for p in seizure_projects
    ]
    return JsonResponse({'models': models})


@csrf_exempt
@require_POST
def seizure_realtime_predict_chunk(request):
    """
    Accept a 10-second signal window as JSON, run inference, return classification.
    Supports single-model and ensemble (majority vote) modes.
    Dev-only — no auth, no logging.

    Body: {
        "data":          {"ch_name": [2000 floats], ...},
        "model_variant": "cnn_simple" | "cnn_transformer" | "gru_attention"
                       | "fusion"    | "ensemble"          (default: "cnn_simple")
    }
    """
    import time
    from projects.inference import get_handler
    from projects.inference.base import InferenceError
    from monitoring.utils import log_prediction

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    signal_data = payload.get('data')
    if not signal_data or not isinstance(signal_data, dict):
        return JsonResponse({'error': 'Missing or invalid "data" field.'}, status=400)

    requested_variant = payload.get('model_variant', 'cnn_simple')

    try:
        df = pd.DataFrame(signal_data)
    except Exception as e:
        return JsonResponse({'error': f'Could not build DataFrame: {e}'}, status=400)

    seizure_projects = [
        p for p in Projects.objects.filter(is_public=True)
        if (p.file_input_config or {}).get('handler') == 'seizure_eeg'
    ]
    if not seizure_projects:
        return JsonResponse({'error': 'No seizure detection model found on server.'}, status=503)

    def _run_project(project, dataframe):
        buf = io.BytesIO()
        dataframe.to_parquet(buf, index=False)
        buf.seek(0)
        buf.name = 'chunk.parquet'
        return get_handler(project).run(buf)

    t0 = time.perf_counter()

    if requested_variant == 'ensemble':
        per_model = []
        for project in seizure_projects:
            variant = (project.file_input_config or {}).get('model_variant', 'unknown')
            try:
                res = _run_project(project, df)
                per_model.append({
                    'variant':    variant,
                    'label':      res.get('prediction_label'),
                    'confidence': round(float(res.get('prediction_proba') or 0), 4),
                    'success':    True,
                })
            except Exception as e:
                per_model.append({'variant': variant, 'success': False, 'error': str(e)})

        ms = int((time.perf_counter() - t0) * 1000)

        good = [r for r in per_model if r.get('success') and r.get('label')]
        if not good:
            return JsonResponse({'error': 'All models failed during ensemble inference.'}, status=500)

        labels   = [r['label'] for r in good]
        votes    = {lbl: labels.count(lbl) for lbl in set(labels)}
        winner   = max(votes, key=votes.get)
        avg_conf = sum(r['confidence'] for r in good if r['label'] == winner) / votes[winner]

        for entry in good:
            proj = next((p for p in seizure_projects
                         if (p.file_input_config or {}).get('model_variant') == entry['variant']), seizure_projects[0])
            log_prediction(
                project=proj, input_type='realtime',
                confidence=entry['confidence'], label=entry['label'],
                inference_ms=ms, success=True, source='realtime', request=request,
            )

        return JsonResponse({
            'label':        winner,
            'confidence':   round(avg_conf, 4),
            'inference_ms': ms,
            'variant':      'ensemble',
            'votes':        votes,
            'per_model':    per_model,
        })

    else:
        project = next(
            (p for p in seizure_projects
             if (p.file_input_config or {}).get('model_variant') == requested_variant),
            None,
        )
        if project is None:
            available = [(p.file_input_config or {}).get('model_variant', '?') for p in seizure_projects]
            return JsonResponse(
                {'error': f'Variant "{requested_variant}" not configured. Available: {available}'},
                status=404,
            )

        try:
            result = _run_project(project, df)
        except InferenceError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Inference error: {type(e).__name__}: {e}'}, status=500)

        ms = int((time.perf_counter() - t0) * 1000)
        log_prediction(
            project=project, input_type='realtime',
            confidence=float(result.get('prediction_proba') or 0),
            label=result.get('prediction_label', ''),
            inference_ms=ms, success=True, source='realtime', request=request,
        )
        return JsonResponse({
            'label':        result.get('prediction_label'),
            'confidence':   round(float(result.get('prediction_proba') or 0), 4),
            'inference_ms': ms,
            'variant':      (project.file_input_config or {}).get('model_variant', 'unknown'),
        })


# ── Editor.js image upload ────────────────────────────────────────────────────
@csrf_exempt
def editor_image_upload(request):
    """
    Used by the Editor.js Image tool in the admin.
    Accepts POST with an 'image' file, saves it, returns the URL.
    Only staff members may upload.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'success': 0, 'message': 'Unauthorized'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': 0, 'message': 'Method not allowed'}, status=405)

    image = request.FILES.get('image')
    if not image:
        return JsonResponse({'success': 0, 'message': 'No image provided'})

    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
    ext = os.path.splitext(image.name)[1].lower()
    if ext not in allowed:
        return JsonResponse({'success': 0, 'message': f'Unsupported format: {ext}'})

    from PersonalPortfolio.storage import image_storage
    storage = image_storage()
    path = storage.save(f'projects/editor_images/{image.name}', image)
    url  = request.build_absolute_uri(storage.url(path))
    return JsonResponse({'success': 1, 'file': {'url': url}})


# ── Error handlers ────────────────────────────────────────────────────────────
def error_404(request, exception=None):
    return render(request, '404.html', status=404)

def error_500(request):
    return render(request, '500.html', status=500)
