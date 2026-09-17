"""OpenAI-compatible LLM client. All errors propagate as LlmError."""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hound.config import Config, resolve_model_name
from hound.models import Artifacts
from hound.analyze import prompts


class LlmError(Exception):
    """Raised when the LLM call fails or returns unusable output."""

    def __init__(self, message: str, *, status_code: int | None = None, usage: dict | None = None, budget_skipped: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.usage = usage or {}
        self.budget_skipped = budget_skipped


#: Shared concurrency throttle across all threads in this process. Replaced
#: (not mutated) so in-flight workers keep a consistent view; soft bound only.
_sem_lock = threading.Lock()
_configured_concurrency = 4
_llm_semaphore = threading.BoundedSemaphore(4)


def set_llm_concurrency(limit: int) -> None:
    """Set the maximum number of simultaneous LLM requests in this process.

    Replaces the shared semaphore so existing holders are unaffected and the
    new limit applies to subsequent acquisitions. Idempotent when unchanged.
    """
    global _configured_concurrency, _llm_semaphore
    limit = max(1, int(limit))
    if limit == _configured_concurrency:
        return
    with _sem_lock:
        if limit != _configured_concurrency:
            _configured_concurrency = limit
            _llm_semaphore = threading.BoundedSemaphore(limit)


def _semaphore_for(config: Config) -> threading.BoundedSemaphore:
    set_llm_concurrency(getattr(config, "max_concurrency", 4))
    return _llm_semaphore


def _make_client(config: Config):
    """Build the right OpenAI-compatible client for the configured provider."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise LlmError("openai package not installed") from exc

    # Hound owns the bounded retry loop below. Disable SDK-level retries so
    # configured attempt and timeout limits remain accurate.
    kwargs: dict = {"api_key": config.api_key or "sk-no-key", "max_retries": 0}
    if config.base_url:
        from hound.providers import validate_base_url

        kwargs["base_url"] = validate_base_url(config.base_url)
    if config.timeout:
        kwargs["timeout"] = config.timeout

    try:
        if config.provider == "azure":
            # Azure OpenAI uses api_version + a deployment id as the model name.
            import os

            kwargs["api_version"] = os.environ.get("AZURE_API_VERSION", "2024-10-21")
            return openai.AzureOpenAI(**kwargs)

        return openai.OpenAI(**kwargs)
    except Exception as exc:
        raise LlmError(f"Failed to create LLM client: {exc}") from exc


def build_request_preview(artifacts: Artifacts, config: Config) -> dict:
    """Build the exact bounded message payload without creating a client."""
    payload: dict = {
        "model": resolve_model_name(config.provider, config.model, base_url=config.base_url),
        "messages": [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.build_user_prompt(artifacts)},
        ],
    }
    if config.max_tokens:
        payload["max_tokens"] = int(config.max_tokens)
    if config.temperature is not None:
        payload["temperature"] = float(config.temperature)
    return payload


def analyze_with_llm(artifacts: Artifacts, config: Config) -> tuple[dict, dict]:
    """Call the LLM and return ``(data_dict, usage_dict)``. Raises LlmError on failure."""
    if config.provider in {"openai-oauth", "claude-oauth", "gemini-oauth"}:
        return _analyze_with_subscription(artifacts, config)
    if _provider_protocol(config.provider) == "anthropic":
        return _analyze_with_anthropic_compatible(artifacts, config)
    client = _make_client(config)
    usage: dict = {}
    account = config.request_account

    def request(**payload):
        if account is not None and not account.admit():
            raise LlmError("LLM request budget exhausted", usage=dict(usage), budget_skipped=True)
        observed = {}
        try:
            response = client.chat.completions.create(**payload)
            observed = _extract_usage(response)
            return response
        except Exception as exc:
            observed = _extract_usage(exc) or _extract_usage(getattr(exc, "body", None))
            if not observed:
                error_response = getattr(exc, "response", None)
                observed = _extract_usage(error_response)
                if not observed and error_response is not None:
                    try:
                        observed = _extract_usage(error_response.json())
                    except (AttributeError, TypeError, ValueError):
                        pass
            raise
        finally:
            for key, value in observed.items():
                usage[key] = usage.get(key, 0) + value
            if account is not None:
                account.observe(observed, config)

    kwargs = build_request_preview(artifacts, config)
    # response_format is not supported by every OpenAI-compatible backend
    # (Ollama, some gateways). Ask for JSON in the prompt, fallback without response_format if rejected.
    resp = None
    semaphore = _semaphore_for(config)
    with semaphore:
        for attempt in range(config.max_retries + 1):
            try:
                try:
                    resp = request(**kwargs, response_format={"type": "json_object"})
                except Exception as exc:
                    if not _unsupported_parameter(exc, "response_format"):
                        raise
                    resp = request(**kwargs)
                break
            except Exception as exc:
                if isinstance(exc, LlmError):
                    raise
                status = getattr(exc, "status_code", None)
                retryable = status in {429, 500, 502, 503, 504} or status is None
                if attempt >= config.max_retries or not retryable:
                    raise LlmError(str(exc), status_code=status, usage=dict(usage)) from exc
                time.sleep(min(2 ** attempt, 8.0))

    try:
        if not resp.choices or not resp.choices[0].message:
            raise LlmError("empty LLM response choices", usage=usage)
        message = resp.choices[0].message
        content = _message_text(message)
    except Exception as exc:
        if isinstance(exc, LlmError):
            raise
        raise LlmError(f"Invalid LLM response structure: {exc}", usage=usage) from exc

    if not content:
        raise LlmError("empty LLM response", usage=usage)
    try:
        data = _parse_json_object(content)
    except json.JSONDecodeError as exc:
        raise LlmError(f"LLM returned invalid JSON: {exc}", usage=usage) from exc
    return data, usage


def _analyze_with_subscription(artifacts: Artifacts, config: Config) -> tuple[dict, dict]:
    from hound.subscription_auth import invoke

    prompt = prompts.SYSTEM_PROMPT + "\n\n" + prompts.build_user_prompt(artifacts)
    schema = {"type": "object", "additionalProperties": True}
    try:
        content = invoke(config.provider, config.model, prompt, schema, config.timeout)
        return _parse_json_object(content), {}
    except Exception as exc:
        if isinstance(exc, LlmError):
            raise
        raise LlmError(str(exc)) from exc


def _provider_protocol(provider: str) -> str:
    from hound.providers import load_custom_providers

    return str(load_custom_providers().get(provider, {}).get("protocol") or "openai")


def _analyze_with_anthropic_compatible(artifacts: Artifacts, config: Config) -> tuple[dict, dict]:
    if not config.base_url or not config.api_key:
        raise LlmError("Anthropic-compatible providers require a base URL and API key")
    from hound.providers import validate_base_url

    base_url = validate_base_url(config.base_url)
    endpoint = f"{base_url}/messages" if base_url.endswith("/v1") else f"{base_url}/v1/messages"
    payload = {
        "model": resolve_model_name(config.provider, config.model, base_url=config.base_url),
        "system": prompts.SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompts.build_user_prompt(artifacts)}],
        "max_tokens": int(config.max_tokens),
        "temperature": float(config.temperature),
    }
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={
        "content-type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urlopen(request, timeout=config.timeout) as response:
            body = json.loads(response.read(4 * 1024 * 1024 + 1))
    except HTTPError as exc:
        raise LlmError(f"provider returned HTTP {exc.code}", status_code=exc.code) from exc
    except (OSError, URLError, ValueError) as exc:
        raise LlmError(f"Anthropic-compatible provider failed: {exc}") from exc
    blocks = body.get("content", []) if isinstance(body, dict) else []
    content = "\n".join(block.get("text", "") for block in blocks if isinstance(block, dict) and block.get("type") == "text")
    usage_raw = body.get("usage", {}) if isinstance(body, dict) else {}
    usage = {
        "prompt_tokens": int(usage_raw.get("input_tokens", 0)),
        "completion_tokens": int(usage_raw.get("output_tokens", 0)),
    }
    usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    try:
        return _parse_json_object(content), usage
    except json.JSONDecodeError as exc:
        raise LlmError(f"LLM returned invalid JSON: {exc}", usage=usage) from exc


def _extract_usage(response: object) -> dict:
    raw = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if raw is None:
        return {}
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw.get(key) if isinstance(raw, dict) else getattr(raw, key, None)
        try:
            if value is not None:
                result[key] = max(0, int(value))
        except (TypeError, ValueError):
            pass
    return result


def _unsupported_parameter(exc: Exception, parameter: str) -> bool:
    """Recognize compatibility errors without retrying unrelated failures."""
    text = str(exc).lower()
    parameter = parameter.lower()
    return parameter in text and any(
        marker in text
        for marker in ("unsupported", "not support", "unknown", "unrecognized", "invalid parameter")
    )


def _message_text(message: object) -> str:
    """Read text from OpenAI-compatible string or content-part responses."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(getattr(part, "text", None), str):
                parts.append(part.text)
        if parts:
            return "\n".join(parts)
    # A few reasoning-oriented OpenAI-compatible gateways place the only text
    # in reasoning_content. Prefer normal content, but do not discard a valid
    # JSON result solely because the gateway used that field.
    reasoning = getattr(message, "reasoning_content", None)
    return reasoning if isinstance(reasoning, str) else ""


def _parse_json_object(content: str) -> dict:
    """Extract one JSON object from strict JSON, fences, or brief wrapper text."""
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as direct_error:
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                value, _end = decoder.raw_decode(text, match.start())
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise direct_error
    if not isinstance(value, dict):
        raise json.JSONDecodeError("LLM returned non-object JSON", text, 0)
    return value
