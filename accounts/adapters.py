"""Social login adapter: write the real reason for a failed Google/GitHub login
to the logs. allauth otherwise shows only "Third-Party Login Failure" and
records nothing, which leaves a broken login undiagnosable in production."""
import logging

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

logger = logging.getLogger('accounts.social')


class LoggingSocialAccountAdapter(DefaultSocialAccountAdapter):
    def on_authentication_error(self, request, provider, error=None, exception=None,
                                extra_context=None):
        # No tokens, codes or secrets are logged: only the provider, allauth's
        # error kind, the exception type and its message (which for OAuth
        # errors is the provider's error code, e.g. "invalid_client").
        logger.warning(
            'Social login failed: provider=%s error=%s exception=%s: %s host=%s',
            getattr(provider, 'id', provider), error,
            type(exception).__name__ if exception else None,
            str(exception)[:300] if exception else '',
            request.get_host(),
        )
        return super().on_authentication_error(request, provider, error=error,
                                               exception=exception,
                                               extra_context=extra_context)
