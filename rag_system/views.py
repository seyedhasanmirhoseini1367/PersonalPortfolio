# rag_system/views.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
import json
from .services.rag_service import RAGService
from .models import QueryLog


class RAGView(View):
    template_name = 'rag_system/chat.html'

    def get(self, request):
        """Render the main chat interface"""
        rag_service = RAGService()
        chat_history = rag_service.get_chat_history(limit=20)

        context = {
            'chat_history': chat_history,
            'document_types': [
                {'value': 'all', 'label': 'All Documents', 'selected': True},
                {'value': 'project', 'label': 'Projects Only'},
                {'value': 'resume', 'label': 'Resume Only'},
                {'value': 'blog', 'label': 'Blog Posts Only'},
                {'value': 'skill', 'label': 'Skills Only'},
            ]
        }
        return render(request, self.template_name, context)


@method_decorator(csrf_exempt, name='dispatch')
class QueryAPIView(View):
    """API endpoint for RAG queries"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            question = data.get('question', '').strip()
            document_type = data.get('document_type', 'all')

            if not question:
                return JsonResponse({
                    'error': 'Question is required'
                }, status=400)

            # Map document type
            if document_type == 'all':
                document_types = None
            else:
                document_types = [document_type]

            rag_service = RAGService()
            result = rag_service.query(question, document_types)

            return JsonResponse({
                'success': True,
                'question': result['question'],
                'answer': result['answer'],
                'sources': result['sources'],
                'query_id': result['query_id'],
                'timestamp': QueryLog.objects.get(id=result['query_id']).created_at.isoformat()
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'Internal server error: {str(e)}'
            }, status=500)


class ChatHistoryAPIView(View):
    """API endpoint to get chat history"""

    def get(self, request):
        try:
            limit = int(request.GET.get('limit', 20))
            rag_service = RAGService()
            history = rag_service.get_chat_history(limit=limit)

            history_data = []
            for entry in history:
                history_data.append({
                    'id': str(entry.id),
                    'question': entry.query,
                    'answer': entry.response,
                    'sources': entry.sources,
                    'timestamp': entry.created_at.isoformat()
                })

            return JsonResponse({
                'success': True,
                'history': history_data
            })

        except Exception as e:
            return JsonResponse({
                'error': f'Internal server error: {str(e)}'
            }, status=500)


# Function-based views for simpler routing
def chat_view(request):
    view = RAGView()
    return view.get(request)


# rag_system/views.py (update the query_api function)
@csrf_exempt
@require_http_methods(["POST"])
def query_api(request):
    try:
        data = json.loads(request.body)
        question = data.get('question', '').strip()
        document_type = data.get('document_type', 'all')

        if not question:
            return JsonResponse({
                'success': False,
                'error': 'Question is required'
            }, status=400)

        # Map document type
        if document_type == 'all':
            document_types = None
        else:
            document_types = [document_type]

        rag_service = RAGService()
        result = rag_service.query(question, document_types)

        # If there was an error in RAG processing
        if not result.get('success', True):
            return JsonResponse({
                'success': False,
                'error': result.get('error', 'Unknown error'),
                'question': result['question'],
                'answer': result['answer'],
                'sources': result['sources'],
                'query_id': result['query_id']
            }, status=500)

        return JsonResponse({
            'success': True,
            'question': result['question'],
            'answer': result['answer'],
            'sources': result['sources'],
            'query_id': result['query_id'],
            'timestamp': QueryLog.objects.get(id=result['query_id']).created_at.isoformat()
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def chat_history(request):
    view = ChatHistoryAPIView()
    return view.get(request)
