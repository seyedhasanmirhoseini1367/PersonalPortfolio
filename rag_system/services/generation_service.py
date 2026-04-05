# rag_system/services/generation_service.py
from django.conf import settings
from typing import List, Dict, Any, Optional


class GenerationService:
    """
    LLM generation service supporting Gemini (free), OpenAI, and Anthropic Claude.
    Priority: Gemini (if free API key available) → Anthropic → OpenAI → Fallback

    Configure in settings.py via:
        GEMINI_API_KEY      -> uses gemini-2.5-flash (free tier)
        OPENAI_API_KEY      -> uses gpt-4o-mini by default
        ANTHROPIC_API_KEY   -> uses claude-haiku-4-5-20251001 by default
    """

    def __init__(self):
        self.gemini_api_key = getattr(settings, 'GEMINI_API_KEY', None)
        self.openai_api_key = getattr(settings, 'OPENAI_API_KEY', None)
        self.anthropic_api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)

        rag_cfg = getattr(settings, 'RAG_CONFIG', {})
        self.openai_model = rag_cfg.get('OPENAI_MODEL', 'gpt-4o-mini')
        self.anthropic_model = rag_cfg.get('ANTHROPIC_MODEL', 'claude-haiku-4-5-20251001')
        self.gemini_model = rag_cfg.get('GEMINI_MODEL', 'models/gemini-2.5-flash')
        self.max_tokens = rag_cfg.get('MAX_TOKENS', 600)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Generate a portfolio-assistant response using retrieved context."""
        system_prompt, user_prompt = self._build_assistant_prompts(query, context_chunks)
        return self._call_llm(system_prompt, user_prompt) or self._fallback_response(query, context_chunks)

    def generate_prediction_interpretation(
            self,
            project_title: str,
            project_description: str,
            model_type: str,
            target_feature: str,
            input_data: Dict[str, Any],
            prediction_result: float,
            context_chunks: List[Dict[str, Any]],
            prediction_label: str = "",
    ) -> str:
        """RAG-augmented domain interpretation. prediction_label is the human label."""
        system_prompt, user_prompt = self._build_interpretation_prompts(
            project_title, project_description, model_type,
            target_feature, input_data, prediction_result, context_chunks,
            prediction_label=prediction_label,
        )
        return self._call_llm(system_prompt, user_prompt) or self._fallback_interpretation(
            project_title, target_feature, prediction_label or str(prediction_result)
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_assistant_prompts(self, query, context_chunks):
        context = self._format_context(context_chunks)
        system_prompt = (
            "You are Hasan's portfolio assistant — a helpful AI that answers questions "
            "about Hasan Mirhoseini, a Data Scientist and ML Engineer based in Tampere, Finland. "
            "Use only the context provided to answer. If the context does not contain enough "
            "information, say so honestly. Be concise, professional, and friendly."
        )
        user_prompt = f"Context from Hasan's portfolio:\n{context}\n\nQuestion: {query}\n\nAnswer:"
        return system_prompt, user_prompt

    def _build_interpretation_prompts(
            self, project_title, project_description, model_type,
            target_feature, input_data, prediction_result, context_chunks,
            prediction_label: str = "",
    ):
        # Get project and its RAG document context
        project_doc_context = ""
        try:
            from projects.models import Projects
            project = Projects.objects.filter(title=project_title).first()
            if project and project.rag_document_processed:
                project_doc_context = project.get_rag_document_context()
                if project_doc_context:
                    project_doc_context = f"\n\n📄 **Project Documentation (from uploaded file):**\n{project_doc_context}\n"
        except Exception as e:
            print(f"Error loading project document context: {e}")

        # Combine regular RAG context with project document context
        context = self._format_context(context_chunks) + project_doc_context

        label_str = prediction_label or str(prediction_result)
        system_prompt = (
            "You are a domain-expert assistant helping interpret machine learning model predictions. "
            "Provide a clear, concise interpretation of the prediction result. "
            "Use the retrieved context and uploaded project documentation to add relevant domain knowledge. "
            "Structure your response: (1) plain-language meaning of the result, "
            "(2) relevant clinical or domain background, (3) important caveats. "
            "Write 3–4 paragraphs. Do not use markdown headers or bullet points."
        )
        items = list(input_data.items())[:30]
        input_summary = "\n".join(f"  - {k}: {v}" for k, v in items)
        if len(input_data) > 30:
            input_summary += f"\n  ... and {len(input_data) - 30} more features"
        user_prompt = (
            f"Project: {project_title}\n"
            f"Description: {project_description[:300]}\n"
            f"Model type: {model_type}\n"
            f"Target variable: {target_feature}\n\n"
            f"Prediction outcome: {label_str} (raw value: {prediction_result})\n\n"
            f"Key input features (sample):\n{input_summary}\n\n"
            f"Relevant background context:\n{context if context else 'No additional context available.'}\n\n"
            "Please provide a domain-appropriate interpretation:"
        )
        return system_prompt, user_prompt

    def _format_context(self, context_chunks):
        if not context_chunks:
            return ""
        return "\n\n".join(
            f"[Source: {c['metadata'].get('document_title', 'Unknown')}]\n{c['content']}"
            for c in context_chunks[:4]
        )

    # ------------------------------------------------------------------
    # LLM callers
    # ------------------------------------------------------------------

    def _call_llm(self, system_prompt, user_prompt) -> Optional[str]:
        """Try Gemini first (free), then Anthropic, then OpenAI."""
        if self.gemini_api_key:
            result = self._call_gemini(system_prompt, user_prompt)
            if result:
                return result

        if self.anthropic_api_key:
            result = self._call_anthropic(system_prompt, user_prompt)
            if result:
                return result

        if self.openai_api_key:
            result = self._call_openai(system_prompt, user_prompt)
            if result:
                return result

        return None

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Google Gemini API — uses google.genai (new SDK)."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.gemini_api_key)
            full_prompt = f"{system_prompt}\n\n{user_prompt}"

            response = client.models.generate_content(
                model=self.gemini_model.replace('models/', ''),
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=self.max_tokens,
                    temperature=0.7,
                ),
            )
            if response and response.text:
                return response.text.strip()
            print("Gemini returned empty response")
            return None

        except ImportError:
            print("google-genai not installed. Run: pip install google-genai")
            return None
        except Exception as e:
            print(f"Gemini API error: {e}")
            return None


    def _call_anthropic(self, system_prompt, user_prompt):
        """Anthropic Claude (anthropic>=0.20)"""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            message = client.messages.create(
                model=self.anthropic_model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        except ImportError:
            print("anthropic package not installed. Run: pip install anthropic")
            return None
        except Exception as e:
            print(f"Anthropic API error: {e}")
            return None

    def _call_openai(self, system_prompt, user_prompt):
        """OpenAI (openai>=1.0)"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except ImportError:
            print("openai package not installed.")
            return None
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return None

    # ------------------------------------------------------------------
    # Fallbacks
    # ------------------------------------------------------------------

    def _fallback_response(self, query, context_chunks):
        if context_chunks:
            top = context_chunks[0]['metadata'].get('document_title', 'my portfolio')
            return (
                f"Based on my portfolio, I have relevant experience related to '{query}'. "
                f"You can find more details in '{top}'. "
                "For full AI responses, configure GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY in settings."
            )
        return (
            f"I'd be happy to answer questions about '{query}'. "
            "Please check my projects or contact me directly."
        )

    def _fallback_interpretation(self, project_title, target_feature, prediction_label):
        return (
            f"Result: {prediction_label} (target: {target_feature}, project: {project_title}). "
            "For a detailed AI interpretation, add GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY to Django settings."
        )