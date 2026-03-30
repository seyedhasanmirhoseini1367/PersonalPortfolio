# rag_system/services/generation_service.py
import openai
from django.conf import settings
from typing import List, Dict, Any
import json


class GenerationService:
    def __init__(self):
        # You can use OpenAI, Hugging Face, or local models
        self.api_key = getattr(settings, 'OPENAI_API_KEY', None)
        self.model = "gpt-3.5-turbo"  # or "gpt-4"

    def generate_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Generate response using LLM with retrieved context"""

        # Prepare context
        context = "\n\n".join([
            f"Source: {chunk['metadata']['document_title']}\nContent: {chunk['content']}"
            for chunk in context_chunks
        ])

        # Create prompt
        prompt = f"""You are Hasan, a Data Scientist and ML Engineer. Use the following context from Hasan's portfolio to answer the question. Be professional, concise, and helpful.

Context:
{context}

Question: {query}

Answer:"""

        # For now, return a simple response (you can integrate with OpenAI API later)
        if self.api_key:
            return self._call_openai(prompt)
        else:
            return self._fallback_response(query, context_chunks)

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API"""
        try:
            openai.api_key = self.api_key
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are Hasan, a helpful Data Science assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return self._fallback_response(prompt)

    def _fallback_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Fallback response when LLM is not available"""
        if context_chunks:
            top_source = context_chunks[0]['metadata']['document_title']
            return f"Based on my portfolio, I have experience with '{query}'. You can find more details in my {top_source}. For specific questions, feel free to contact me!"
        else:
            return f"I'd be happy to tell you about {query}! While I don't have specific information in my knowledge base right now, I have extensive experience in data science and machine learning. Please check my projects or contact me for more details."