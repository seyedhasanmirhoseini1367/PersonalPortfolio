# rag_system/services/generation_service.py
"""
LLM generation service — supports:
  • Gemini (google-genai)   — free tier, preferred
  • Anthropic Claude        — fallback
  • OpenAI                  — fallback

Both regular (full response) and streaming (token-by-token) modes are supported.
Conversation history is injected into every prompt for multi-turn context.
"""
import logging
from typing import Any, Dict, Generator, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Type alias for a single conversation turn
HistoryItem = Dict[str, str]   # {"role": "user"|"assistant", "content": "..."}


class GenerationService:

    def __init__(self):
        cfg = getattr(settings, 'RAG_CONFIG', {})
        self.gemini_api_key    = getattr(settings, 'GEMINI_API_KEY', None)
        self.openai_api_key    = getattr(settings, 'OPENAI_API_KEY', None)
        self.anthropic_api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        self.groq_api_key      = getattr(settings, 'GROQ_API_KEY', None)
        self.openai_model      = cfg.get('OPENAI_MODEL', 'gpt-4o-mini')
        self.anthropic_model   = cfg.get('ANTHROPIC_MODEL', 'claude-haiku-4-5-20251001')
        self.gemini_model      = cfg.get('GEMINI_MODEL', 'gemini-2.5-flash')
        self.groq_model        = cfg.get('GROQ_MODEL', 'llama-3.1-8b-instant')
        self.max_tokens        = cfg.get('MAX_TOKENS', 800)

    # ── Public: non-streaming ─────────────────────────────────────────────────

    def generate_response(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        history: Optional[List[HistoryItem]] = None,
        route: str = "general",
    ) -> str:
        system_prompt, messages = self._build_messages(query, context_chunks, history, route=route)
        return (
            self._call_llm(system_prompt, messages)
            or self._fallback_response(query, context_chunks)
        )

    # ── Public: streaming ─────────────────────────────────────────────────────

    def generate_streaming(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        history: Optional[List[HistoryItem]] = None,
        route: str = "general",
    ) -> Generator[str, None, None]:
        """
        Yields text tokens one by one.
        Falls back to yielding the full response at once if streaming is unavailable.
        """
        system_prompt, messages = self._build_messages(query, context_chunks, history, route=route)

        yielded = False

        def _track(gen):
            nonlocal yielded
            for token in gen:
                yielded = True
                yield token

        if self.groq_api_key:
            yield from _track(self._stream_groq(system_prompt, messages))
        elif self.gemini_api_key:
            yield from _track(self._stream_gemini(system_prompt, messages))
        elif self.anthropic_api_key:
            yield from _track(self._stream_anthropic(system_prompt, messages))
        elif self.openai_api_key:
            yield from _track(self._stream_openai(system_prompt, messages))

        # If nothing was yielded (no keys, or all LLMs failed) — emit fallback
        if not yielded:
            yield self._fallback_response(query, context_chunks)

    # ── Prediction interpretation (non-streaming, used by project views) ──────

    def generate_prediction_interpretation(
        self,
        project_title: str,
        project_description: str,
        model_type: str,
        target_feature: str,
        input_data: Dict[str, Any],
        prediction_result: float,
        context_chunks: List[Dict[str, Any]],
        prediction_label: str = '',
    ) -> str:
        system_prompt, messages = self._build_interpretation_messages(
            project_title, project_description, model_type,
            target_feature, input_data, prediction_result,
            context_chunks, prediction_label,
        )
        return (
            self._call_llm(system_prompt, messages)
            or self._fallback_interpretation(project_title, target_feature, prediction_label or str(prediction_result))
        )

    # ── Prompt builders ───────────────────────────────────────────────────────

    def _build_messages(
        self,
        query: str,
        context_chunks: List[Dict[str, Any]],
        history: Optional[List[HistoryItem]],
        route: str = "general",
    ):
        """
        Returns (system_prompt, messages_list) where messages_list is in
        OpenAI/Anthropic format: [{"role": ..., "content": ...}, ...]
        """
        if route == "conversational":
            system_prompt = (
                "You are Hasan's portfolio assistant — a friendly AI that answers questions "
                "about Hasan Mirhoseini, a Data Scientist and ML Engineer based in Helsinki, Finland. "
                "This is a conversational follow-up — no new context has been retrieved. "
                "Answer naturally using the conversation history above. "
                "Be concise and friendly."
            )
        elif route == "job_fit":
            system_prompt = (
                "You are an expert technical recruiter specialising in ML engineering and data science.\n\n"

                "STEP 1 — Establish the competency standard:\n"
                "Before looking at Hasan, define what the role or question actually requires.\n"
                "• If the user pasted a job description: extract its key requirements as your rubric.\n"
                "• If the user asked about a general role (e.g. 'senior ML engineer', 'data scientist'): "
                "define the typical competency bar for that role — covering technical depth "
                "(ML theory, coding, MLOps/production), experience markers, and soft skills.\n"
                "State this rubric briefly at the top of your answer.\n\n"

                "STEP 2 — Evaluate Hasan against the standard:\n"
                "The context below contains Hasan's CV/resume as the PRIMARY evidence source, "
                "followed by project documentation and skills. "
                "Map each requirement from Step 1 to Hasan's actual evidence.\n\n"

                "STEP 3 — Structure your response exactly like this:\n"
                "**Role Standard: [Role Title]**\n"
                "2–3 lines summarising what this role genuinely requires.\n\n"
                "**Overall Fit: X%**\n\n"
                "**Strong Matches**\n"
                "- per requirement Hasan clearly meets — cite his evidence\n\n"
                "**Partial Matches / Transferable**\n"
                "- areas where he partially meets the bar or has transferable experience\n\n"
                "**Honest Gaps**\n"
                "- requirements not evidenced in the portfolio — be direct, not diplomatic\n\n"
                "**Verdict**\n"
                "1–2 sentences a hiring manager could act on.\n\n"
                "Be evidence-based and honest. Do not invent information not present in the context. "
                "Do not inflate the assessment — gaps are valuable feedback."
            )
        else:
            system_prompt = (
                "You are Hasan's portfolio assistant — an expert AI that answers questions "
                "about Hasan Mirhoseini, a Data Scientist and ML Engineer based in Helsinki, Finland. "
                "Use only the provided context to answer. If context is insufficient, say so honestly. "
                "Be concise, professional, and friendly. Format your answers with Markdown when helpful "
                "(lists, bold, code blocks)."
            )

        context_text = self._format_context(context_chunks)
        context_block = f"Context from Hasan's portfolio:\n{context_text}\n\n" if context_text else ""

        messages: List[HistoryItem] = []

        # Inject last N conversation turns for multi-turn context
        if history:
            for turn in history[-6:]:   # last 3 Q&A pairs
                messages.append({'role': turn['role'], 'content': turn['content']})

        # Current question with injected context
        messages.append({'role': 'user', 'content': f"{context_block}Question: {query}"})

        return system_prompt, messages

    def _build_interpretation_messages(
        self, project_title, project_description, model_type,
        target_feature, input_data, prediction_result,
        context_chunks, prediction_label,
    ):
        label_str = prediction_label or str(prediction_result)

        # Optionally enrich with uploaded project doc context
        extra = ''
        try:
            from projects.models import Projects
            project = Projects.objects.filter(title=project_title).first()
            if project and getattr(project, 'rag_document_processed', False):
                doc_ctx = project.get_rag_document_context()
                if doc_ctx:
                    extra = f"\n\nProject Documentation:\n{doc_ctx}"
        except Exception:
            pass

        context_text = self._format_context(context_chunks) + extra

        system_prompt = (
            "You are a domain-expert assistant interpreting machine learning model predictions. "
            "Provide a clear, structured interpretation: "
            "(1) plain-language meaning, (2) domain background, (3) important caveats. "
            "Write 3–4 concise paragraphs. Do not use markdown headers or bullet points."
        )

        items = list(input_data.items())[:30]
        input_summary = '\n'.join(f'  {k}: {v}' for k, v in items)
        if len(input_data) > 30:
            input_summary += f'\n  ... and {len(input_data) - 30} more features'

        user_content = (
            f"Project: {project_title}\n"
            f"Description: {project_description[:300]}\n"
            f"Model type: {model_type}\n"
            f"Target variable: {target_feature}\n"
            f"Prediction outcome: {label_str} (raw: {prediction_result})\n\n"
            f"Key input features:\n{input_summary}\n\n"
            f"Relevant context:\n{context_text or 'No additional context available.'}\n\n"
            "Please interpret this result:"
        )

        return system_prompt, [{'role': 'user', 'content': user_content}]

    def _format_context(self, chunks: List[Dict[str, Any]]) -> str:
        if not chunks:
            return ''
        return '\n\n'.join(
            f"[Source: {c['metadata'].get('document_title', 'Unknown')} "
            f"({c['metadata'].get('document_type', '')})]\n{c['content']}"
            for c in chunks[:5]
        )

    # ── Non-streaming LLM calls ───────────────────────────────────────────────

    def _call_llm(self, system_prompt: str, messages: List[HistoryItem]) -> Optional[str]:
        for caller in (self._call_groq, self._call_gemini, self._call_anthropic, self._call_openai):
            try:
                result = caller(system_prompt, messages)
                if result:
                    return result
            except Exception as exc:
                logger.warning('LLM call failed (%s): %s', caller.__name__, exc)
        return None

    def _call_groq(self, system_prompt: str, messages: List[HistoryItem]) -> Optional[str]:
        if not self.groq_api_key:
            return None
        try:
            from groq import Groq
            client = Groq(api_key=self.groq_api_key)
            response = client.chat.completions.create(
                model=self.groq_model,
                messages=[{'role': 'system', 'content': system_prompt}] + messages,
                max_tokens=self.max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except ImportError:
            logger.warning('groq package not installed. Run: pip install groq')
            return None
        except Exception as exc:
            logger.warning('Groq error: %s', exc)
            return None

    def _call_gemini(self, system_prompt: str, messages: List[HistoryItem]) -> Optional[str]:
        if not self.gemini_api_key:
            return None
        try:
            from google import genai
            from google.genai import types

            client  = genai.Client(api_key=self.gemini_api_key)
            history = self._to_gemini_history(messages[:-1])
            latest  = messages[-1]['content']

            response = client.models.generate_content(
                model=self.gemini_model,
                contents=history + [latest],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.max_tokens,
                    temperature=0.7,
                ),
            )
            return (response.text or '').strip() or None
        except ImportError:
            logger.warning('google-genai not installed. Run: pip install google-genai')
            return None
        except Exception as exc:
            logger.warning('Gemini error: %s', exc)
            return None

    def _call_anthropic(self, system_prompt: str, messages: List[HistoryItem]) -> Optional[str]:
        if not self.anthropic_api_key:
            return None
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            msg = client.messages.create(
                model=self.anthropic_model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
            )
            return msg.content[0].text
        except ImportError:
            logger.warning('anthropic package not installed.')
            return None
        except Exception as exc:
            logger.warning('Anthropic error: %s', exc)
            return None

    def _call_openai(self, system_prompt: str, messages: List[HistoryItem]) -> Optional[str]:
        if not self.openai_api_key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[{'role': 'system', 'content': system_prompt}] + messages,
                max_tokens=self.max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except ImportError:
            logger.warning('openai package not installed.')
            return None
        except Exception as exc:
            logger.warning('OpenAI error: %s', exc)
            return None

    # ── Streaming LLM calls ───────────────────────────────────────────────────

    def _stream_groq(
        self, system_prompt: str, messages: List[HistoryItem]
    ) -> Generator[str, None, None]:
        if not self.groq_api_key:
            return
        try:
            from groq import Groq
            client = Groq(api_key=self.groq_api_key)
            stream = client.chat.completions.create(
                model=self.groq_model,
                messages=[{'role': 'system', 'content': system_prompt}] + messages,
                max_tokens=self.max_tokens,
                temperature=0.7,
                stream=True,
            )
            for chunk in stream:
                text = chunk.choices[0].delta.content or ''
                if text:
                    yield text
        except ImportError:
            logger.warning('groq not installed, falling back.')
            yield from self._stream_gemini(system_prompt, messages)
        except Exception as exc:
            logger.warning('Groq stream error: %s', exc)
            yield from self._stream_gemini(system_prompt, messages)

    def _stream_gemini(
        self, system_prompt: str, messages: List[HistoryItem]
    ) -> Generator[str, None, None]:
        if not self.gemini_api_key:
            yield from self._stream_anthropic(system_prompt, messages)
            return
        try:
            from google import genai
            from google.genai import types

            client  = genai.Client(api_key=self.gemini_api_key)
            history = self._to_gemini_history(messages[:-1])
            latest  = messages[-1]['content']

            for chunk in client.models.generate_content_stream(
                model=self.gemini_model,
                contents=history + [latest],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.max_tokens,
                    temperature=0.7,
                ),
            ):
                text = getattr(chunk, 'text', '') or ''
                if text:
                    yield text

        except ImportError:
            logger.warning('google-genai not installed, falling back.')
            yield from self._stream_anthropic(system_prompt, messages)
        except Exception as exc:
            logger.warning('Gemini stream error: %s', exc)
            yield from self._stream_anthropic(system_prompt, messages)

    def _stream_anthropic(
        self, system_prompt: str, messages: List[HistoryItem]
    ) -> Generator[str, None, None]:
        if not self.anthropic_api_key:
            yield from self._stream_openai(system_prompt, messages)
            return
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            with client.messages.stream(
                model=self.anthropic_model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text

        except ImportError:
            logger.warning('anthropic not installed, falling back to OpenAI.')
            yield from self._stream_openai(system_prompt, messages)
        except Exception as exc:
            logger.warning('Anthropic stream error: %s', exc)
            yield from self._stream_openai(system_prompt, messages)

    def _stream_openai(
        self, system_prompt: str, messages: List[HistoryItem]
    ) -> Generator[str, None, None]:
        if not self.openai_api_key:
            return
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.openai_api_key)
            stream = client.chat.completions.create(
                model=self.openai_model,
                messages=[{'role': 'system', 'content': system_prompt}] + messages,
                max_tokens=self.max_tokens,
                temperature=0.7,
                stream=True,
            )
            for chunk in stream:
                text = chunk.choices[0].delta.content or ''
                if text:
                    yield text

        except ImportError:
            logger.warning('openai not installed.')
        except Exception as exc:
            logger.warning('OpenAI stream error: %s', exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_gemini_history(messages: List[HistoryItem]) -> List[str]:
        """Flatten prior turns into a list of strings for Gemini's `contents`."""
        result = []
        for m in messages:
            prefix = 'User: ' if m['role'] == 'user' else 'Assistant: '
            result.append(prefix + m['content'])
        return result

    # ── Fallbacks ─────────────────────────────────────────────────────────────

    def _fallback_response(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        if context_chunks:
            top = context_chunks[0]['metadata'].get('document_title', 'the portfolio')
            return (
                f"I found relevant information in **{top}** related to your question. "
                "The AI provider is temporarily unavailable — please try again in a moment. "
                "(Configure GROQ_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY to enable responses.)"
            )
        return (
            "I'm happy to answer questions about Hasan's portfolio, but the AI provider is "
            "temporarily unavailable. Please try again in a moment."
        )

    def _fallback_interpretation(self, project_title: str, target: str, label: str) -> str:
        return (
            f"Prediction: **{label}** (target: {target}, project: {project_title}). "
            "Configure an LLM API key for a detailed domain interpretation."
        )
