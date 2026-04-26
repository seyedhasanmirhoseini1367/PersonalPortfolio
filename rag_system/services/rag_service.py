# rag_system/services/rag_service.py
"""
Orchestration layer — ties retrieval + generation together.

query()        → full response (used by legacy query_api endpoint)
stream_query() → generator yielding SSE-formatted strings (used by stream_api)
"""
import json
import logging
import traceback
from typing import Any, Dict, Generator, List, Optional

from .retrieval_service import RetrievalService
from .generation_service import GenerationService
from ..models import ChatSession, QueryLog

logger = logging.getLogger(__name__)


class RAGService:

    def __init__(self):
        self.retrieval   = RetrievalService()
        self.generation  = GenerationService()

    # ── History helper ────────────────────────────────────────────────────────

    def _get_history(self, session: Optional[ChatSession]) -> List[Dict[str, str]]:
        """
        Return the last 6 messages (3 Q&A turns) from a session as
        [{"role": "user"|"assistant", "content": "..."}, ...] for context injection.
        """
        if session is None:
            return []
        turns = []
        for log in session.messages.order_by('-created_at')[:6]:
            turns.append({'role': 'assistant', 'content': log.response})
            turns.append({'role': 'user',      'content': log.query})
        turns.reverse()   # oldest first
        return turns

    # ── Session helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_session(session_id: Optional[str]) -> ChatSession:
        """Return existing session or create a new one."""
        if session_id:
            try:
                return ChatSession.objects.get(id=session_id)
            except (ChatSession.DoesNotExist, Exception):
                pass
        return ChatSession.objects.create(title='New Chat')

    @staticmethod
    def _auto_title(session: ChatSession, question: str) -> None:
        """Set the session title from the first question if still default."""
        if session.title == 'New Chat' and session.messages.count() <= 1:
            session.title = question[:80] + ('…' if len(question) > 80 else '')
        session.save(update_fields=['title', 'updated_at'])

    # ── Non-streaming query (backward compat) ─────────────────────────────────

    def query(
        self,
        question: str,
        document_types: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = self._resolve_session(session_id)
        history = self._get_history(session)

        try:
            chunks   = self.retrieval.hybrid_retrieve(question, document_types)
            response = self.generation.generate_response(question, chunks, history=history)

            log = QueryLog.objects.create(
                session=session,
                query=question,
                response=response,
                sources=[c['metadata'] for c in chunks],
            )
            self._auto_title(session, question)

            return {
                'success':       True,
                'question':      question,
                'answer':        response,
                'sources':       chunks,
                'query_id':      str(log.id),
                'session_id':    str(session.id),
                'session_title': session.title,
            }

        except Exception as exc:
            traceback.print_exc()
            log = QueryLog.objects.create(
                session=session,
                query=question,
                response=f'Error: {exc}',
                sources=[],
            )
            return {
                'success':    False,
                'error':      str(exc),
                'question':   question,
                'answer':     f'Sorry, I encountered an error: {exc}',
                'sources':    [],
                'query_id':   str(log.id),
                'session_id': str(session.id),
            }

    # ── Streaming query ───────────────────────────────────────────────────────

    def stream_query(
        self,
        question: str,
        document_types: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Yields SSE-formatted strings:
            data: {"type": "token",   "content": "..."}\\n\\n
            data: {"type": "sources", "sources": [...], "session_id": "...", ...}\\n\\n
            data: {"type": "done"}\\n\\n
            data: {"type": "error",   "message": "..."}\\n\\n
        """
        session  = self._resolve_session(session_id)
        history  = self._get_history(session)
        full_text = ''

        def _sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        try:
            # Step 1: classify the query → get the right document types to search.
            # We run only the router (zero LLM calls, pure keyword matching) so
            # there is no latency cost before streaming starts.
            if document_types is None:
                from rag_system.graph.nodes import router_node
                route = router_node({"question": question}).get("route", "general")
                _ROUTE_DOC_TYPES = {
                    "cv":       ["resume", "skill", "project"],
                    "thesis":   ["project_documentation", "project"],
                    "ml_model": ["project", "project_documentation"],
                    "projects": ["project", "project_documentation", "resume"],
                    "general":  None,   # None = search everything
                    "job_fit":  ["resume", "skill", "project", "project_documentation"],
                }
                resolved_types = _ROUTE_DOC_TYPES.get(route)
                logger.debug("stream_query: routed to '%s' → types=%s", route, resolved_types)
            else:
                route = "general"
                resolved_types = document_types

            # Step 2: retrieve the right chunks for the classified route.
            top_k = 8 if route == "job_fit" else 5
            chunks = self.retrieval.hybrid_retrieve(question, resolved_types, top_k=top_k)

            # Step 3: grade relevance — skip for comprehensive listing routes.
            _SKIP_GRADING = {'cv', 'projects', 'job_fit'}
            if document_types is None and route not in _SKIP_GRADING:
                from rag_system.graph.nodes import grade_relevance
                chunks = grade_relevance(question, chunks)

            # Step 4: stream the answer token by token.
            for token in self.generation.generate_streaming(question, chunks, history=history, route=route):
                full_text += token
                yield _sse({'type': 'token', 'content': token})

            # Persist completed exchange
            log = QueryLog.objects.create(
                session=session,
                query=question,
                response=full_text,
                sources=[c['metadata'] for c in chunks],
            )
            self._auto_title(session, question)

            # Send sources + session metadata as one final event
            serialisable_sources = [
                {
                    'metadata':   c['metadata'],
                    'similarity': round(c.get('similarity', 0), 4),
                }
                for c in chunks
            ]
            yield _sse({
                'type':          'sources',
                'sources':       serialisable_sources,
                'query_id':      str(log.id),
                'session_id':    str(session.id),
                'session_title': session.title,
            })
            yield _sse({'type': 'done'})

        except Exception as exc:
            traceback.print_exc()
            logger.exception('stream_query error: %s', exc)
            # Save partial response if we got any tokens
            if full_text:
                QueryLog.objects.create(
                    session=session,
                    query=question,
                    response=full_text,
                    sources=[],
                )
            yield _sse({'type': 'error', 'message': str(exc)})
            yield _sse({'type': 'done'})

    # ── Prediction interpretation ─────────────────────────────────────────────

    def interpret_prediction(
        self,
        project,
        input_data: Dict[str, Any],
        prediction_result: float,
        prediction_label: str = '',
    ) -> Dict[str, Any]:
        try:
            label_str = prediction_label or str(prediction_result)
            retrieval_query = (
                f"{project.title} {project.description[:150]} "
                f"{project.target_feature} {label_str}"
            )
            chunks = self.retrieval.hybrid_retrieve(
                retrieval_query,
                document_types=['project', 'project_documentation', 'skill', 'resume'],
            )
            interpretation = self.generation.generate_prediction_interpretation(
                project_title=project.title,
                project_description=project.description,
                model_type=project.get_model_type_display() if project.model_type else 'ML Model',
                target_feature=project.target_feature,
                input_data=input_data,
                prediction_result=prediction_result,
                prediction_label=label_str,
                context_chunks=chunks,
            )
            return {
                'success':        True,
                'interpretation': interpretation,
                'sources':        [c['metadata'] for c in chunks],
            }
        except Exception as exc:
            traceback.print_exc()
            return {
                'success':        False,
                'interpretation': f'Interpretation unavailable: {exc}',
                'sources':        [],
            }

    # ── LangGraph query ───────────────────────────────────────────────────────

    def langgraph_query(
        self,
        question: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the question through the LangGraph pipeline:
          router → search node → generate → verify (→ retry if needed) → END

        Returns the same dict format as query() for drop-in compatibility.
        """
        session = self._resolve_session(session_id)
        history = self._get_history(session)

        try:
            from rag_system.graph.graph import rag_graph

            initial_state = {
                "question":      question,
                "route":         "general",
                "answer":        "",
                "context_chunks": [],
                "session_id":    str(session.id),
                "history":       history,
                "ml_prediction": None,
                "needs_retry":   False,
                "retry_count":   0,
            }

            final_state = rag_graph.invoke(initial_state)

            answer = final_state.get("answer", "")
            chunks = final_state.get("context_chunks", [])
            route  = final_state.get("route", "general")

            log = QueryLog.objects.create(
                session=session,
                query=question,
                response=answer,
                sources=[c['metadata'] for c in chunks],
            )
            self._auto_title(session, question)

            return {
                'success':       True,
                'question':      question,
                'answer':        answer,
                'sources':       chunks,
                'route':         route,
                'query_id':      str(log.id),
                'session_id':    str(session.id),
                'session_title': session.title,
            }

        except Exception as exc:
            traceback.print_exc()
            log = QueryLog.objects.create(
                session=session,
                query=question,
                response=f'Error: {exc}',
                sources=[],
            )
            return {
                'success':    False,
                'error':      str(exc),
                'question':   question,
                'answer':     f'Sorry, I encountered an error: {exc}',
                'sources':    [],
                'query_id':   str(log.id),
                'session_id': str(session.id),
            }

    # ── Legacy ───────────────────────────────────────────────────────────────

    def get_chat_history(self, limit: int = 20):
        return QueryLog.objects.order_by('-created_at')[:limit]
