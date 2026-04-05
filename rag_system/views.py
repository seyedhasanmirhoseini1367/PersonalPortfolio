# rag_system/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

from .services.rag_service import RAGService
from .models import QueryLog, ChatSession


# ── Page view ──────────────────────────────────────────────────────────────────

def chat_view(request):
    """Render the main chat interface (no history preloaded — sidebar fetches via JS)."""
    context = {
        'document_types': [
            {'value': 'all',     'label': 'All Documents',  'selected': True},
            {'value': 'project', 'label': 'Projects Only'},
            {'value': 'resume',  'label': 'Resume Only'},
            {'value': 'blog',    'label': 'Blog Posts Only'},
            {'value': 'skill',   'label': 'Skills Only'},
        ]
    }
    return render(request, 'rag_system/chat.html', context)


# ── Session API ────────────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
@csrf_exempt
def sessions_api(request):
    """
    GET  → list all sessions ordered by last updated
    POST → create a new empty session, return its id
    """
    if request.method == 'GET':
        sessions = ChatSession.objects.all().order_by('-updated_at')
        data = []
        for s in sessions:
            last = s.messages.order_by('-created_at').first()
            data.append({
                'id':         str(s.id),
                'title':      s.title,
                'created_at': s.created_at.isoformat(),
                'updated_at': s.updated_at.isoformat(),
                'message_count': s.messages.count(),
                'preview':    (last.query[:60] + '…' if last and len(last.query) > 60 else last.query) if last else '',
            })
        return JsonResponse({'success': True, 'sessions': data})

    # POST — create new session
    session = ChatSession.objects.create(title='New Chat')
    return JsonResponse({
        'success': True,
        'session': {
            'id':    str(session.id),
            'title': session.title,
        }
    })


@require_http_methods(["GET", "PATCH", "DELETE"])
@csrf_exempt
def session_detail_api(request, session_id):
    """
    GET    → return all messages in the session (oldest first)
    PATCH  → rename the session  { "title": "New title" }
    DELETE → delete the session and all its messages
    """
    try:
        session = ChatSession.objects.get(id=session_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session not found'}, status=404)

    if request.method == 'DELETE':
        session.delete()
        return JsonResponse({'success': True})

    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        title = data.get('title', '').strip()
        if not title:
            return JsonResponse({'error': 'Title cannot be empty'}, status=400)
        session.title = title[:200]
        session.save(update_fields=['title', 'updated_at'])
        return JsonResponse({'success': True, 'title': session.title})

    # GET — return messages
    messages = session.messages.order_by('created_at')
    data = []
    for m in messages:
        data.append({
            'id':        str(m.id),
            'question':  m.query,
            'answer':    m.response,
            'sources':   m.sources,
            'timestamp': m.created_at.isoformat(),
        })
    return JsonResponse({
        'success': True,
        'session': {'id': str(session.id), 'title': session.title},
        'messages': data,
    })


# ── Query API ──────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def query_api(request):
    """
    Accepts JSON body:
        question      (str, required)
        document_type (str, default "all")
        session_id    (str UUID, optional — if omitted a new session is auto-created)
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    question = data.get('question', '').strip()
    if not question:
        return JsonResponse({'success': False, 'error': 'Question is required'}, status=400)

    document_type = data.get('document_type', 'all')
    document_types = None if document_type == 'all' else [document_type]

    # Resolve or create session
    session_id = data.get('session_id', '').strip()
    session = None
    if session_id:
        try:
            session = ChatSession.objects.get(id=session_id)
        except ChatSession.DoesNotExist:
            pass

    if session is None:
        session = ChatSession.objects.create(title='New Chat')

    # Run RAG
    rag_service = RAGService()
    result = rag_service.query(question, document_types)

    # Link the created QueryLog to this session and update session title
    try:
        log = QueryLog.objects.get(id=result['query_id'])
        log.session = session
        log.save(update_fields=['session'])

        # Auto-title session from its first message
        if session.title == 'New Chat' and session.messages.count() == 1:
            title = question[:80] + ('…' if len(question) > 80 else '')
            session.title = title
        # Always bump updated_at
        session.save(update_fields=['title', 'updated_at'])

    except QueryLog.DoesNotExist:
        pass

    base_response = {
        'question':   result['question'],
        'answer':     result['answer'],
        'sources':    result['sources'],
        'query_id':   result['query_id'],
        'session_id': str(session.id),
        'session_title': session.title,
    }

    try:
        log_obj = QueryLog.objects.get(id=result['query_id'])
        base_response['timestamp'] = log_obj.created_at.isoformat()
    except QueryLog.DoesNotExist:
        pass

    if not result.get('success', True):
        base_response['success'] = False
        base_response['error'] = result.get('error', 'Unknown error')
        return JsonResponse(base_response, status=500)

    base_response['success'] = True
    return JsonResponse(base_response)


# ── Legacy history endpoint (kept for backward compat) ─────────────────────────

@require_http_methods(["GET"])
def chat_history(request):
    limit = int(request.GET.get('limit', 20))
    rag_service = RAGService()
    history = rag_service.get_chat_history(limit=limit)
    history_data = [{
        'id':        str(e.id),
        'question':  e.query,
        'answer':    e.response,
        'sources':   e.sources,
        'timestamp': e.created_at.isoformat(),
    } for e in history]
    return JsonResponse({'success': True, 'history': history_data})
