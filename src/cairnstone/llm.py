"""Thin OpenAI-compatible client for the local TensorFold endpoints.

No cloud, no API keys beyond `Authorization: Bearer local`. The stable
instruction block must live in its own leading system message so TensorFold's
per-message-boundary prefix cache hits (see docs/tensorfold-integration.md).
"""

import json
import time
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8460/v1"
DEFAULT_MODEL = "glm-5.3-flash"


class LLMError(Exception):
    """The endpoint failed or returned an unusable response."""


class Telemetry:
    """Engine telemetry for the last call (R5: engine ledger)."""

    def __init__(self):
        self.calls = 0
        self.last = {}

    def record(self, data, elapsed):
        tf = data.get("tensorfold", {}) or {}
        usage = data.get("usage", {}) or {}
        details = (usage.get("prompt_tokens_details") or {}) or {}
        self.last = {
            "engine": tf.get("engine"),
            "tokens_per_second": tf.get("tokens_per_second"),
            "prefill_seconds": tf.get("prefill_seconds"),
            "time_to_first_token": tf.get("time_to_first_token"),
            "cached_tokens": details.get("cached_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "elapsed_seconds": round(elapsed, 3),
        }
        self.calls += 1

    def as_dict(self):
        return dict(self.last)


class LLMClient:
    """OpenAI-compatible chat client for a local endpoint."""

    def __init__(self, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL,
                 api_key="local", timeout=300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.telemetry = Telemetry()

    def chat(self, messages, model=None, max_tokens=1024, think=False,
             temperature=0.0):
        """POST /chat/completions. Sends chat_template_kwargs so TensorFold
        honours the thinking flag (a top-level flag is silently ignored)."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": think},
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % self.api_key,
            },
            method="POST",
        )
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # urllib, HTTP, JSON errors
            raise LLMError("chat request failed: %s" % exc) from exc
        self.telemetry.record(data, time.monotonic() - start)
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed response: %r" % (data,)) from exc
        return content

    def telemetry_last(self):
        return self.telemetry.as_dict()
