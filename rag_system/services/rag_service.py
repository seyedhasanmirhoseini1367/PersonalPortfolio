# rag_system/services/rag_service.py
from typing import Dict, Any, List, Optional
from .retrieval_service import RetrievalService
from .generation_service import GenerationService
from ..models import QueryLog
import traceback


class RAGService:
    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.generation_service = GenerationService()

    def query(self, question: str, document_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Main RAG query method"""
        try:
            print(f"RAG Query: {question}, document_types: {document_types}")

            # Retrieve relevant chunks
            retrieved_chunks = self.retrieval_service.hybrid_retrieve(question, document_types)
            print(f"Retrieved {len(retrieved_chunks)} chunks")

            # Generate response
            response = self.generation_service.generate_response(question, retrieved_chunks)
            print(f"Generated response: {response[:100]}...")

            # Log the query
            query_log = QueryLog.objects.create(
                query=question,
                response=response,
                sources=[chunk['metadata'] for chunk in retrieved_chunks]
            )

            return {
                'success': True,
                'question': question,
                'answer': response,
                'sources': retrieved_chunks,
                'query_id': str(query_log.id)
            }

        except Exception as e:
            error_msg = f"Error in RAG query: {str(e)}"
            print(error_msg)
            traceback.print_exc()

            # Log the error
            query_log = QueryLog.objects.create(
                query=question,
                response=f"Error: {str(e)}",
                sources=[]
            )

            return {
                'success': False,
                'error': error_msg,
                'question': question,
                'answer': f"Sorry, I encountered an error while processing your question: {str(e)}",
                'sources': [],
                'query_id': str(query_log.id)
            }

    def get_chat_history(self, limit: int = 10):
        """Get recent chat history"""
        return QueryLog.objects.all().order_by('-created_at')[:limit]
