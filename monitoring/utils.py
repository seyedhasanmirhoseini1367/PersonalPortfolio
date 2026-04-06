"""
Utility: call log_prediction() from any view that runs inference.
Keeps monitoring logic out of business logic.
"""
import time
import logging

logger = logging.getLogger(__name__)


def log_prediction(*, project, user=None, input_data=None, input_type='web',
                   prediction=None, confidence=None, label='',
                   inference_ms=None, success=True, error_message='',
                   request=None, source='web'):
    """
    Fire-and-forget: save a PredictionLog row.
    Never raises — monitoring must not break the app.
    """
    try:
        from .models import PredictionLog
        ip = ua = ''
        if request:
            xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip  = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
            ua  = request.META.get('HTTP_USER_AGENT', '')[:500]

        PredictionLog.objects.create(
            project       = project,
            user          = user if (user and user.is_authenticated) else None,
            input_data    = input_data or {},
            input_type    = input_type,
            prediction    = prediction,
            confidence    = confidence,
            label         = label,
            inference_ms  = inference_ms,
            success       = success,
            error_message = error_message,
            source        = source,
            ip_address    = ip or None,
            user_agent    = ua,
        )
    except Exception as exc:
        logger.warning(f'log_prediction failed silently: {exc}')
