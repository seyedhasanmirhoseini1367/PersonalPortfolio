# projects/inference/azure_ml_client.py
"""
Azure ML Managed Online Endpoint client.

Usage:
    client = AzureMLClient()
    result = client.predict({"data": [...]})   # returns dict or None

Returns None gracefully when:
  - env vars not configured
  - endpoint is unreachable
  - timeout
  - any other error

Caller is responsible for falling back to local model when None is returned.

Required Django settings (set via env vars):
    AZURE_ML_ENDPOINT_URL  — e.g. https://<endpoint>.inference.ml.azure.com/score
    AZURE_ML_ENDPOINT_KEY  — primary or secondary key from Azure ML endpoint
"""

import json
import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


class AzureMLClient:
    """
    Thin wrapper around an Azure ML managed online endpoint.
    All errors are caught and logged — never raises.
    """

    def __init__(self):
        self.endpoint_url = getattr(settings, 'AZURE_ML_ENDPOINT_URL', '') or ''
        self.endpoint_key = getattr(settings, 'AZURE_ML_ENDPOINT_KEY', '') or ''

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint_url and self.endpoint_key)

    def predict(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        POST data to Azure ML endpoint and return the parsed response.

        Args:
            data: dict — will be JSON-serialised as the request body.

        Returns:
            Parsed JSON response as dict, or None if unavailable.
        """
        if not self.is_configured:
            logger.debug("Azure ML endpoint not configured — skipping.")
            return None

        headers = {
            "Authorization": f"Bearer {self.endpoint_key}",
            "Content-Type":  "application/json",
        }

        try:
            response = requests.post(
                self.endpoint_url,
                headers=headers,
                data=json.dumps(data),
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.warning("Azure ML endpoint timed out after %ss.", _TIMEOUT_SECONDS)
            return None

        except requests.exceptions.ConnectionError as exc:
            logger.warning("Azure ML endpoint connection error: %s", exc)
            return None

        except requests.exceptions.HTTPError as exc:
            logger.warning(
                "Azure ML endpoint HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return None

        except Exception as exc:
            logger.warning("Azure ML endpoint unexpected error: %s", exc)
            return None
