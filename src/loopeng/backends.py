"""Fail-closed OpenRouter proposal adapter.

The only network operation in this project is made by this host-side client.
Untrusted source code never receives the API key and is not executed here.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class BackendError(RuntimeError):
    """A model request failed or did not satisfy its response contract."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward an Authorization header, including within the same host.
        return None


SE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "enum": ["ledger.py"]},
        "source": {"type": "string"},
    },
    "required": ["path", "source"],
    "additionalProperties": False,
}

RD_SCHEMA = {
    "type": "object",
    "properties": {
        "feature_map": {"type": "string", "enum": ["linear", "interaction", "quadratic"]},
        "lr": {"type": "number"},
        "l2": {"type": "number"},
        "epochs": {"type": "integer"},
    },
    "required": ["feature_map", "lr", "l2", "epochs"],
    "additionalProperties": False,
}


class OpenRouterChat:
    """One non-streaming request per proposal, with explicit structured output.

    No automatic retries: a timed-out request can still be billable. The caller
    journals each attempted API request *before* calling this adapter.
    """

    API_ROOT = "https://openrouter.ai/api/v1"
    MAX_BODY_BYTES = 2_000_000

    def __init__(self, model: str | None = None, timeout: int | None = None):
        self.model = (model or os.getenv("OPENROUTER_MODEL", "")).strip()
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not self.model or not self.api_key:
            raise BackendError("Set OPENROUTER_MODEL and OPENROUTER_API_KEY")
        try:
            self.timeout = int(timeout or os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45"))
            self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "3500"))
        except ValueError:
            raise BackendError("OpenRouter timeout and token limit must be integers") from None
        if not 3 <= self.timeout <= 180 or not 100 <= self.max_tokens <= 12000:
            raise BackendError("OpenRouter timeout/token limit outside supported bounds")
        self.opener = urllib.request.build_opener(_NoRedirect())

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "X-Title": "Loop Engineering Demos",
        }
        referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
        if referer:
            if not referer.startswith("https://"):
                raise BackendError("OPENROUTER_HTTP_REFERER must be HTTPS")
            headers["HTTP-Referer"] = referer
        return headers

    def _fetch(self, path: str, payload: dict | None = None) -> dict:
        if path not in ("/chat/completions", "/key", "/models"):
            raise BackendError("Unsupported OpenRouter endpoint")
        limit = 15_000_000 if path == "/models" else self.MAX_BODY_BYTES
        request = urllib.request.Request(
            self.API_ROOT + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="GET" if payload is None else "POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            # Provider bodies can echo inputs. Never print body, URL query or key.
            raise BackendError(f"OpenRouter returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BackendError(f"OpenRouter connection failed ({type(exc).__name__})") from None
        if len(raw) > limit:
            raise BackendError("OpenRouter response exceeded size limit")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise BackendError("OpenRouter returned invalid JSON transport data") from None
        if not isinstance(document, dict):
            raise BackendError("OpenRouter response was not an object")
        return document

    def preflight(self) -> dict:
        """GET-only account/model check; does not validate a live inference route."""
        account = self._fetch("/key").get("data") or {}
        models = self._fetch("/models").get("data") or []
        match = next(
            (item for item in models if isinstance(item, dict) and item.get("id") == self.model),
            None,
        )
        if match is None:
            raise BackendError("Model not listed for this account; check the exact ID")
        supported = match.get("supported_parameters") or []
        return {
            "model": self.model,
            "model_listed": True,
            "advertises_structured_outputs": (
                "structured_outputs" in supported or "response_format" in supported
            ),
            "key_label_suffix": str(account.get("label") or "")[-4:],
            "limit_remaining": account.get("limit_remaining"),
            "note": "GET-only check; run preflight --probe to test inference (billable).",
        }

    def ask_json(self, instructions: str, prompt: str, schema: dict | None = None) -> tuple[dict, dict]:
        """Make one billable request, returning an object and safe usage metadata."""
        if not isinstance(schema, dict) or not schema.get("properties"):
            raise BackendError("An explicit JSON object schema is required")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "proposal", "strict": True, "schema": schema},
            },
            "provider": {"require_parameters": True, "data_collection": "deny"},
            "usage": {"include": True},
        }
        if os.getenv("OPENROUTER_REQUIRE_ZDR", "0") == "1":
            payload["provider"]["zdr"] = True

        result = self._fetch("/chat/completions", payload)
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise BackendError("OpenRouter returned no completion choice")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise BackendError("Model output incomplete or terminated abnormally")
        message = choice.get("message") or {}
        if not isinstance(message, dict) or message.get("refusal"):
            raise BackendError("Model refused or returned an invalid response")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise BackendError("No JSON content in model response")
        try:
            obj = json.loads(content)
        except ValueError:
            raise BackendError("Model output was not valid JSON") from None
        if not isinstance(obj, dict):
            raise BackendError("Model output must be a JSON object")
        keys = set(schema["properties"])
        if set(obj) != keys or not set(schema.get("required", ())).issubset(obj):
            raise BackendError("Model output violated the root JSON schema")
        # Domain-specific, strict type/range validation occurs in the proposer policy.
        usage = result.get("usage") or {}
        try:
            input_tokens = max(0, int(usage.get("prompt_tokens") or 0))
            output_tokens = max(0, int(usage.get("completion_tokens") or 0))
        except (ValueError, TypeError):
            input_tokens = output_tokens = 0
        amount = usage.get("cost")
        try:
            cost_usd = float(amount) if amount is not None else None
            if cost_usd is not None and not 0 <= cost_usd < 1e9:
                cost_usd = None
        except (TypeError, ValueError):
            cost_usd = None
        return obj, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": str(result.get("model") or self.model),
            "generation_id": str(result.get("id") or ""),
            "cost_usd_reported": cost_usd,
        }


def make_backend(backend: str) -> OpenRouterChat:
    if backend != "openrouter":
        raise BackendError(f"Unknown backend: {backend}")
    return OpenRouterChat()
