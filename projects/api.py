"""
REST API for model inference.
Exposes project predictions as JSON endpoints — no authentication required for GET,
POST requires a valid project with prediction_endpoint=True and has_api=True.

Endpoints:
  GET  /api/models/                  — list all public API-enabled models
  GET  /api/models/<id>/             — model info + input schema
  POST /api/models/<id>/predict/     — run inference, returns JSON result
"""
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from .models import Projects


def _model_info(project):
    return {
        'id':               project.pk,
        'title':            project.title,
        'description':      project.short_description,
        'model_type':       project.get_model_type_display() if project.model_type else None,
        'evaluation_metric': project.evaluation_metric or None,
        'accuracy_score':   project.accuracy_score,
        'avg_inference_ms': project.avg_inference_ms,
        'input_type':       project.prediction_input_type,
        'input_schema':     project.input_features,
        'endpoint':         f'/api/models/{project.pk}/predict/',
    }


def api_model_list(request):
    """GET /api/models/ — list all public models with API enabled."""
    projects = Projects.objects.filter(is_public=True, has_api=True, prediction_endpoint=True)
    return JsonResponse({
        'count':   projects.count(),
        'models': [_model_info(p) for p in projects],
    })


def api_model_detail(request, project_id):
    """GET /api/models/<id>/ — model metadata and input schema."""
    project = get_object_or_404(Projects, pk=project_id, is_public=True, has_api=True)
    return JsonResponse(_model_info(project))


@csrf_exempt
@require_http_methods(['POST'])
def api_predict(request, project_id):
    """
    POST /api/models/<id>/predict/

    For manual-input models send JSON body:
        {"feature1": value1, "feature2": value2, ...}

    For file-upload models send multipart/form-data with key "file".

    Returns:
        {"success": true, "prediction": ..., "confidence": ..., "label": ..., "inference_ms": ...}
    """
    import time
    project = get_object_or_404(Projects, pk=project_id, is_public=True,
                                has_api=True, prediction_endpoint=True)

    t0 = time.perf_counter()

    try:
        from .runner import run_prediction as _run_prediction
        from django.test import RequestFactory

        if project.prediction_input_type == 'file':
            uploaded = request.FILES.get('file')
            if not uploaded:
                return JsonResponse({'success': False, 'error': 'No file provided. Send file as multipart/form-data with key "file".'}, status=400)
            result = _run_prediction(project, uploaded_file=uploaded)
        else:
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)
            result = _run_prediction(project, input_data=body)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        return JsonResponse({
            'success':      True,
            'prediction':   result.get('prediction'),
            'confidence':   result.get('confidence'),
            'label':        result.get('label'),
            'inference_ms': elapsed_ms,
            'model_id':     project.pk,
            'model_title':  project.title,
        })

    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)
