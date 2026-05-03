"""
Management command: test LLM provider connectivity.
Usage: python manage.py test_llm
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Test connectivity to each configured LLM provider."

    def handle(self, **options):
        groq_key    = getattr(settings, 'GROQ_API_KEY', '')
        gemini_key  = getattr(settings, 'GEMINI_API_KEY', '')
        openai_key  = getattr(settings, 'OPENAI_API_KEY', '')
        anthropic_key = getattr(settings, 'ANTHROPIC_API_KEY', '')

        self.stdout.write(f"GROQ_API_KEY    : {'SET (' + groq_key[:8] + '...)' if groq_key else 'NOT SET'}")
        self.stdout.write(f"GEMINI_API_KEY  : {'SET (' + gemini_key[:8] + '...)' if gemini_key else 'NOT SET'}")
        self.stdout.write(f"OPENAI_API_KEY  : {'SET' if openai_key else 'NOT SET'}")
        self.stdout.write(f"ANTHROPIC_API_KEY: {'SET' if anthropic_key else 'NOT SET'}")
        self.stdout.write("")

        if groq_key:
            self._test_groq(groq_key)
        if gemini_key:
            self._test_gemini(gemini_key)
        if anthropic_key:
            self._test_anthropic(anthropic_key)

    def _test_groq(self, key):
        self.stdout.write("Testing Groq (llama-3.1-8b-instant, streaming)...")
        try:
            from groq import Groq
            client = Groq(api_key=key)
            stream = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": "Say OK in one word"}],
                max_tokens=5,
                stream=True,
            )
            tokens = []
            for chunk in stream:
                t = chunk.choices[0].delta.content or ''
                if t:
                    tokens.append(t)
            result = ''.join(tokens)
            if result:
                self.stdout.write(self.style.SUCCESS(f"  Groq streaming OK: {result}"))
            else:
                self.stdout.write(self.style.ERROR("  Groq streaming FAIL: no tokens yielded"))
        except ImportError:
            self.stdout.write(self.style.ERROR("  Groq FAIL: groq package not installed"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Groq FAIL: {e}"))

    def _test_gemini(self, key):
        self.stdout.write("Testing Gemini...")
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Say OK",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            self.stdout.write(self.style.SUCCESS(f"  Gemini OK: {resp.text}"))
        except ImportError:
            self.stdout.write(self.style.ERROR("  Gemini FAIL: google-genai package not installed"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Gemini FAIL: {e}"))

    def _test_anthropic(self, key):
        self.stdout.write("Testing Anthropic...")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=5,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            self.stdout.write(self.style.SUCCESS(f"  Anthropic OK: {msg.content[0].text}"))
        except ImportError:
            self.stdout.write(self.style.ERROR("  Anthropic FAIL: anthropic package not installed"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Anthropic FAIL: {e}"))
