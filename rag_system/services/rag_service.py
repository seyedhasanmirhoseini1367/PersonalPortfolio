# rag_system/services/rag_service.py
from typing import Dict, Any, List, Optional
from .retrieval_service import RetrievalService
from .generation_service import GenerationService
from ..models import QueryLog
import traceback


class RAGService:
    def __init__(self):
        self.retrieval_service  = RetrievalService()
        self.generation_service = GenerationService()

    def query(self, question: str, document_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Main RAG query for the portfolio assistant chat."""
        try:
            retrieved_chunks = self.retrieval_service.hybrid_retrieve(question, document_types)
            response = self.generation_service.generate_response(question, retrieved_chunks)

            query_log = QueryLog.objects.create(
                query=question,
                response=response,
                sources=[c['metadata'] for c in retrieved_chunks]
            )
            return {
                'success': True,
                'question': question,
                'answer': response,
                'sources': retrieved_chunks,
                'query_id': str(query_log.id)
            }
        except Exception as e:
            traceback.print_exc()
            query_log = QueryLog.objects.create(query=question, response=f"Error: {e}", sources=[])
            return {
                'success': False,
                'error': str(e),
                'question': question,
                'answer': f"Sorry, I encountered an error: {e}",
                'sources': [],
                'query_id': str(query_log.id)
            }

    def interpret_prediction(
        self,
        project,
        input_data: Dict[str, Any],
        prediction_result: float,
        prediction_label: str = "",
    ) -> Dict[str, Any]:
        """
        RAG-powered interpretation of a model prediction result.
        prediction_label is passed so the LLM sees the human-readable outcome
        (e.g. "Seizure activity detected") not just a raw number.
        """
        try:
            label_str = prediction_label or str(prediction_result)

            # Build retrieval query: domain + outcome for better context retrieval
            retrieval_query = (
                f"{project.title} {project.description[:150]} "
                f"{project.target_feature} {label_str}"
            )
            context_chunks = self.retrieval_service.hybrid_retrieve(
                retrieval_query,
                document_types=['project', 'project_documentation', 'skill', 'resume']
            )

            interpretation = self.generation_service.generate_prediction_interpretation(
                project_title=project.title,
                project_description=project.description,
                model_type=project.get_model_type_display() if project.model_type else "ML Model",
                target_feature=project.target_feature,
                input_data=input_data,
                prediction_result=prediction_result,
                prediction_label=label_str,
                context_chunks=context_chunks,
            )
            return {
                'success': True,
                'interpretation': interpretation,
                'sources': [c['metadata'] for c in context_chunks],
            }
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'interpretation': f"Interpretation unavailable: {e}",
                'sources': [],
            }

    def get_chat_history(self, limit: int = 10):
        return QueryLog.objects.all().order_by('-created_at')[:limit]
