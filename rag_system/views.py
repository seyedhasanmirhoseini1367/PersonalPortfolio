# rag_system/views.py
import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ChatSession, QueryLog
from .services.rag_service import RAGService

logger = logging.getLogger(__name__)


# ── Page view ──────────────────────────────────────────────────────────────────

def chat_view(request):
    return render(request, 'rag_system/chat.html', {
        'document_types': [
            {'value': 'all',                    'label': 'All Documents',        'selected': True},
            {'value': 'project',                'label': 'Projects'},
            {'value': 'project_documentation',  'label': 'Project Docs'},
            {'value': 'resume',                 'label': 'Resume'},
            {'value': 'blog',                   'label': 'Blog Posts'},
            {'value': 'skill',                  'label': 'Skills'},
        ]
    })


# ── Streaming query (primary path) ────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['POST'])
def stream_api(request):
    """
    POST  { question, document_type?, session_id? }
    Returns text/event-stream  (Server-Sent Events).

    Events emitted:
        data: {"type": "token",   "content": "..."}
        data: {"type": "sources", "sources": [...], "session_id": "...", "session_title": "..."}
        data: {"type": "done"}
        data: {"type": "error",   "message": "..."}
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, Exception):
        def _err():
            yield 'data: {"type":"error","message":"Invalid JSON"}\n\n'
            yield 'data: {"type":"done"}\n\n'
        return StreamingHttpResponse(_err(), content_type='text/event-stream')

    question      = data.get('question', '').strip()
    document_type = data.get('document_type', 'all')
    session_id    = data.get('session_id', '').strip() or None

    if not question:
        def _err():
            yield 'data: {"type":"error","message":"Question is required"}\n\n'
            yield 'data: {"type":"done"}\n\n'
        return StreamingHttpResponse(_err(), content_type='text/event-stream')

    document_types = None if document_type == 'all' else [document_type]

    rag     = RAGService()
    stream  = rag.stream_query(question, document_types, session_id)

    response = StreamingHttpResponse(stream, content_type='text/event-stream')
    response['Cache-Control']     = 'no-cache'
    response['X-Accel-Buffering'] = 'no'   # disable nginx buffering
    return response


# ── Non-streaming query (kept for backward compat / fallback) ─────────────────

@csrf_exempt
@require_http_methods(['POST'])
def query_api(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    question = data.get('question', '').strip()
    if not question:
        return JsonResponse({'success': False, 'error': 'Question is required'}, status=400)

    document_type  = data.get('document_type', 'all')
    document_types = None if document_type == 'all' else [document_type]
    session_id     = data.get('session_id', '').strip() or None
    use_langgraph  = data.get('use_langgraph', False)

    rag = RAGService()
    if use_langgraph:
        result = rag.langgraph_query(question, session_id=session_id)
    else:
        result = rag.query(question, document_types, session_id=session_id)

    if not result.get('success', True):
        return JsonResponse(result, status=500)
    return JsonResponse(result)


# ── Session API ────────────────────────────────────────────────────────────────

@require_http_methods(['GET', 'POST'])
@csrf_exempt
def sessions_api(request):
    if request.method == 'GET':
        sessions = ChatSession.objects.all().order_by('-updated_at')
        data = []
        for s in sessions:
            last = s.messages.order_by('-created_at').first()
            data.append({
                'id':            str(s.id),
                'title':         s.title,
                'created_at':    s.created_at.isoformat(),
                'updated_at':    s.updated_at.isoformat(),
                'message_count': s.messages.count(),
                'preview': (
                    (last.query[:60] + '…' if len(last.query) > 60 else last.query)
                    if last else ''
                ),
            })
        return JsonResponse({'success': True, 'sessions': data})

    # POST — create new session
    session = ChatSession.objects.create(title='New Chat')
    return JsonResponse({
        'success': True,
        'session': {'id': str(session.id), 'title': session.title},
    })


@require_http_methods(['GET', 'PATCH', 'DELETE'])
@csrf_exempt
def session_detail_api(request, session_id):
    try:
        session = ChatSession.objects.get(id=session_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)

    if request.method == 'DELETE':
        session.delete()
        return JsonResponse({'success': True})

    if request.method == 'PATCH':
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        title = body.get('title', '').strip()
        if not title:
            return JsonResponse({'error': 'Title cannot be empty'}, status=400)
        session.title = title[:200]
        session.save(update_fields=['title', 'updated_at'])
        return JsonResponse({'success': True, 'title': session.title})

    # GET — return messages oldest-first
    messages = session.messages.order_by('created_at')
    return JsonResponse({
        'success': True,
        'session': {'id': str(session.id), 'title': session.title},
        'messages': [
            {
                'id':        str(m.id),
                'question':  m.query,
                'answer':    m.response,
                'sources':   m.sources,
                'timestamp': m.created_at.isoformat(),
            }
            for m in messages
        ],
    })


# ── Legacy history endpoint ────────────────────────────────────────────────────

@require_http_methods(['GET'])
def chat_history(request):
    limit   = int(request.GET.get('limit', 20))
    history = RAGService().get_chat_history(limit=limit)
    return JsonResponse({
        'success': True,
        'history': [
            {
                'id':        str(e.id),
                'question':  e.query,
                'answer':    e.response,
                'sources':   e.sources,
                'timestamp': e.created_at.isoformat(),
            }
            for e in history
        ],
    })
