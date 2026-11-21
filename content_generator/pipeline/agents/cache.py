"""Cache for analysis steps whose result depends only on their inputs.

The brand profile, competitor gap map and intent classification are the
same for every format of one submission (and for repeat runs on the same
company material), but each used to cost a model call per format.
"""
import hashlib
import json
from datetime import timedelta

from django.utils import timezone

TTL = timedelta(days=7)
VERSION = 1   # bump when a prompt changes so old results are not reused


def _key(kind: str, parts) -> str:
    raw = json.dumps([VERSION, kind, parts], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def cached(kind: str, parts, compute, model_cls=None):
    """Return the cached result for (kind, parts) or compute and store it.

    compute() returns a pydantic model (model_cls) or a plain dict.
    Any cache problem falls back to computing, never breaks the run.
    """
    from content_generator.models import AnalysisCache
    key = _key(kind, parts)
    try:
        hit = AnalysisCache.objects.filter(key=key, created_at__gte=timezone.now() - TTL).first()
        if hit is not None:
            print(f"  (reused cached {kind})")
            return model_cls(**hit.data) if model_cls else hit.data
    except Exception:
        hit = None
    value = compute()
    try:
        data = value.model_dump() if hasattr(value, 'model_dump') else value
        AnalysisCache.objects.update_or_create(key=key, defaults={'kind': kind, 'data': data})
    except Exception:
        pass
    return value
