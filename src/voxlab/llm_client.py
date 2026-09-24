"""Minimal DeepInfra chat-completions client for the automatic-baselines track.

This module makes real external API calls. It is intentionally separate from
the rest of the pipeline (audit/provenance/expansion/agreement/consensus),
which is 100% standard-library and makes no network calls by design. No LLM
is a classifier anywhere else in this project; this file exists only for the
automatic-baselines experimental track (see docs/automatic_experiments.md).

The API key is read from the environment (or a local .env, never committed)
and is never logged, printed, or written to any output file.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEEPINFRA_ENDPOINT = "https://api.deepinfra.com/v1/openai/chat/completions"
DEEPINFRA_MODELS_ENDPOINT = "https://api.deepinfra.com/v1/openai/models"
ENV_VAR = "DEEPINFRA_API_KEY"


def _load_dotenv(root: Path) -> None:
    """Populate os.environ from a local .env if the var isn't already set."""
    if os.environ.get(ENV_VAR):
        return
    path = root / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == ENV_VAR:
            os.environ[ENV_VAR] = value.strip()


def _api_key(root: Path) -> str:
    _load_dotenv(root)
    key = os.environ.get(ENV_VAR)
    if not key:
        raise RuntimeError(
            f"{ENV_VAR} is not set. Define it in the environment or in a local "
            f".env file (never commit it)."
        )
    return key


RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def _request(root: Path, url: str, payload: dict | None) -> dict:
    key = _api_key(root)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    max_attempts = 6
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        request = urllib.request.Request(
            url,
            data=data,
            method="POST" if payload is not None else "GET",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRYABLE_HTTP_CODES and attempt < max_attempts - 1:
                last_error = RuntimeError(f"DeepInfra request failed ({exc.code}): {body}")
                time.sleep(min(2 ** attempt, 30))
                continue
            raise RuntimeError(f"DeepInfra request failed ({exc.code}): {body}") from None
        except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"DeepInfra request failed after {max_attempts} attempts: {last_error}") from None


def list_models(root: Path) -> list[str]:
    """Confirm real model identifiers before freezing the experiment manifest."""
    result = _request(root, DEEPINFRA_MODELS_ENDPOINT, None)
    return [item["id"] for item in result.get("data", [])]


def chat_completion(
    root: Path, model: str, messages: list[dict[str, str]],
    temperature: float = 0.0, seed: int | None = None,
) -> dict:
    """Return the raw parsed JSON response from a chat completion call."""
    payload = {"model": model, "messages": messages, "temperature": temperature}
    if seed is not None:
        payload["seed"] = seed
    return _request(root, DEEPINFRA_ENDPOINT, payload)


def completion_text(response: dict) -> str:
    return response["choices"][0]["message"]["content"]
