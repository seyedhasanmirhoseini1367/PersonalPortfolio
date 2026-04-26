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

Per-model endpoint settings (for multi-model setups):
    EEG_RT_ENDPOINT_URL     / EEG_RT_ENDPOINT_KEY
    EEG_EXT_ENDPOINT_URL    / EEG_EXT_ENDPOINT_KEY

ARCHITECTURE LESSON — why a managed endpoint?
──────────────────────────────────────────────
Your Django app runs on a small server (no GPU, limited RAM). The EEG model
is 3.2M params — fine for CPU but slow. Azure ML gives you:

  1. Separate compute: the model runs on its own container, not inside Django.
  2. Auto-scaling: Azure adds more instances under load.
  3. Health checks + restart: if the container crashes, Azure restarts it.
  4. Versioned deployments: push model v2 with 10% traffic, verify, then 100%.
  5. Monitoring: latency, error rate, throughput in Azure Monitor dashboard.

Django calls the endpoint with a plain requests.post() — the Azure SDK is only
needed at deployment time, not at runtime.

FALLBACK PATTERN (used in eeg_foundation.py):
──────────────────────────────────────────────
  client = AzureMLClient.for_task("rt")
  result = client.predict({"data": arr.tolist()})
  if result is None:
      # Azure not configured or unreachable — run locally
      result = local_inference(arr)
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

    @classmethod
    def for_task(cls, task: str) -> "AzureMLClient":
        """
        Return a client configured for a specific EEG task.
        Uses per-task env vars if set, falls back to the generic endpoint.

        Usage:
            client = AzureMLClient.for_task("rt")         # Challenge 1
            client = AzureMLClient.for_task("externalizing")  # Challenge 2
        """
        task_map = {
            "rt":            ("EEG_RT_ENDPOINT_URL",  "EEG_RT_ENDPOINT_KEY"),
            "externalizing": ("EEG_EXT_ENDPOINT_URL", "EEG_EXT_ENDPOINT_KEY"),
        }
        url_key, api_key = task_map.get(task, ("AZURE_ML_ENDPOINT_URL", "AZURE_ML_ENDPOINT_KEY"))

        instance = cls()
        instance.endpoint_url = getattr(settings, url_key, '') or instance.endpoint_url
        instance.endpoint_key = getattr(settings, api_key, '') or instance.endpoint_key
        return instance
