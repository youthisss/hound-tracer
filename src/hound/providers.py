"""Global OpenAI-compatible provider registry and model discovery."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml
from platformdirs import user_cache_path, user_config_path

from hound.fsio import atomic_write, read_bounded_text
from hound.pathutil import path_has_symlink
from hound.urlutil import validate_http_url

PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_REGISTRY_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 2 * 1024 * 1024
MAX_CACHED_MODELS = 5000
MAX_MODEL_ID_CHARS = 256
REGISTRY_PATH = user_config_path("hound") / "providers.yml"
CACHE_PATH = user_cache_path("hound") / "models.json"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(_NoRedirect()).open


def validate_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("base URL must be an HTTP(S) URL")
    value = value.rstrip("/")
    return validate_http_url(value, label="base URL")


def load_custom_providers(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("provider registry must not use symlinked paths")
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > MAX_REGISTRY_BYTES:
            raise ValueError("provider registry exceeds the 1 MiB limit")
        data = yaml.safe_load(read_bounded_text(path, MAX_REGISTRY_BYTES, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"could not read provider registry: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("provider registry root must be a mapping")
    version = data.get("version", 1)
    if version != 1:
        raise ValueError("provider registry version must be 1")
    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("provider registry must contain a providers mapping")
    result: dict[str, dict] = {}
    for key, value in providers.items():
        provider_id = str(key)
        if not PROVIDER_ID.fullmatch(provider_id):
            raise ValueError(f"provider registry contains invalid provider ID: {provider_id!r}")
        if not isinstance(value, dict):
            raise ValueError(f"provider registry entry {provider_id!r} must be a mapping")
        base_url = validate_base_url(str(value.get("base_url", "")))
        models = value.get("models", [])
        try:
            _validate_model_list(models)
        except ValueError as exc:
            raise ValueError(f"provider registry entry {provider_id!r}.models is invalid") from exc
        default_model = value.get("default_model", "")
        if not isinstance(default_model, str):
            raise ValueError(f"provider registry entry {provider_id!r}.default_model must be a string")
        supports_discovery = value.get("supports_model_discovery", True)
        if not isinstance(supports_discovery, bool):
            raise ValueError(f"provider registry entry {provider_id!r}.supports_model_discovery must be boolean")
        protocol = str(value.get("protocol") or "openai")
        if protocol not in {"openai", "anthropic"}:
            raise ValueError(f"provider registry entry {provider_id!r}.protocol must be openai or anthropic")
        result[provider_id] = {
            "name": str(value.get("name") or provider_id),
            "base_url": base_url,
            "default_model": default_model,
            "models": sorted(set(models), key=str.lower),
            "supports_model_discovery": False if protocol == "anthropic" else supports_discovery,
            "protocol": protocol,
        }
    return result


def save_custom_provider(provider_id: str, definition: dict, path: Path = REGISTRY_PATH) -> None:
    if not PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("provider ID must use lowercase letters, digits, hyphen, or underscore")
    if not isinstance(definition, dict):
        raise ValueError("provider definition must be a mapping")
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("provider registry must not use symlinked paths")
    base_url = validate_base_url(str(definition.get("base_url", "")))
    models = definition.get("models", [])
    _validate_model_list(models)
    supports_discovery = definition.get("supports_model_discovery", True)
    if not isinstance(supports_discovery, bool):
        raise ValueError("supports_model_discovery must be boolean")
    protocol = str(definition.get("protocol") or "openai")
    if protocol not in {"openai", "anthropic"}:
        raise ValueError("protocol must be openai or anthropic")
    providers = load_custom_providers(path)
    providers[provider_id] = {
        "name": str(definition.get("name") or provider_id),
        "base_url": base_url,
        "default_model": str(definition.get("default_model") or ""),
        "models": sorted(set(models), key=str.lower),
        "supports_model_discovery": False if protocol == "anthropic" else supports_discovery,
        "protocol": protocol,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({"version": 1, "providers": providers}, sort_keys=False))


def provider_supports_model_discovery(provider_id: str) -> bool:
    """Return the registry capability without performing network discovery."""
    from hound.config import PROVIDERS

    definition = PROVIDERS.get(provider_id)
    if definition is None:
        definition = load_custom_providers().get(provider_id, {})
    return definition.get("supports_model_discovery", True) is not False


def remove_custom_provider(provider_id: str, path: Path = REGISTRY_PATH) -> None:
    if not PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("provider ID is invalid")
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("provider registry must not use symlinked paths")
    providers = load_custom_providers(path)
    providers.pop(provider_id, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, yaml.safe_dump({"version": 1, "providers": providers}, sort_keys=False))


def discover_models(
    base_url: str,
    api_key: str = "",
    timeout: float = 10.0,
    *,
    provider: str | None = None,
    discovery_url: str | None = None,
) -> list[str]:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0.1 <= float(timeout) <= 120.0:
        raise ValueError("model discovery timeout must be between 0.1 and 120 seconds")
    base_url = validate_base_url(base_url)
    if provider in {"anthropic", "azure"} and discovery_url is None:
        raise ValueError(f"provider {provider} does not support generic model discovery; configure a model/deployment")
    if discovery_url is not None:
        endpoint = validate_base_url(discovery_url)
    elif provider == "gemini" or (
        provider is None
        and base_url.lower().startswith("https://generativelanguage.googleapis.com/v1beta/openai")
    ):
        # Gemini's OpenAI-compatible base already contains ``/v1beta/openai``.
        endpoint = f"{base_url}/models"
    else:
        endpoint = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with urlopen(Request(endpoint, headers=headers), timeout=float(timeout)) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("authentication failed") from exc
        raise ValueError(f"provider returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise ValueError(f"provider unavailable: {exc}") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("model response is too large")
    try:
        data = json.loads(raw)
        raw_models = data.get("data", []) if isinstance(data, dict) else []
        models = sorted({
            item["id"].strip()
            for item in raw_models
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
            and len(item["id"]) <= MAX_MODEL_ID_CHARS
            and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in item["id"])
        }, key=str.lower)
        _validate_model_list(models)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("provider returned an invalid model catalog") from exc
    if not models:
        raise ValueError("provider returned no models")
    return models[:5000]


def check_anthropic_compatible(base_url: str, api_key: str, model: str, timeout: float = 10.0) -> None:
    if not api_key:
        raise ValueError("API key is required")
    if not model.strip():
        raise ValueError("model ID is required")
    base_url = validate_base_url(base_url)
    endpoint = f"{base_url}/messages" if base_url.endswith("/v1") else f"{base_url}/v1/messages"
    payload = json.dumps({
        "model": model.strip(),
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "Reply with OK"}],
    }).encode("utf-8")
    request = Request(endpoint, data=payload, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            if not 200 <= int(response.status) < 300:
                raise ValueError(f"provider returned HTTP {response.status}")
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("authentication failed") from exc
        raise ValueError(f"provider returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise ValueError(f"provider unavailable: {exc}") from exc


def cache_models(provider_id: str, base_url: str, models: list[str], path: Path = CACHE_PATH) -> None:
    if not PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("provider ID is invalid")
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("model cache must not use symlinked paths")
    base_url = validate_base_url(base_url)
    data: dict[str, dict] = {}
    if path.exists():
        try:
            if path.stat().st_size > MAX_CACHE_BYTES:
                raise ValueError("model cache exceeds the 2 MiB limit")
            loaded = json.loads(read_bounded_text(path, MAX_CACHE_BYTES, encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("cache root must be an object")
            data = loaded
        except (OSError, ValueError, TypeError):
            _quarantine_cache(path)
            data = {}
    _validate_model_list(models)
    data[provider_id] = {"base_url": base_url, "models": models, "updated_at": time.time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(data, indent=2))


def cached_models(provider_id: str, path: Path = CACHE_PATH, base_url: str | None = None) -> list[str]:
    """Return cached catalog entries for a provider and, optionally, its URL.

    A provider ID can be reused with a different gateway. In that case its old
    catalog must not silently select a model from the previous gateway.
    """
    if not PROVIDER_ID.fullmatch(provider_id) or path_has_symlink(path) or path.is_symlink():
        return []
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            raise ValueError("model cache exceeds the 2 MiB limit")
        data = json.loads(read_bounded_text(path, MAX_CACHE_BYTES, encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("cache root must be an object")
        entry = data.get(provider_id, {})
        if not isinstance(entry, dict):
            raise ValueError("cache entry must be an object")
        if base_url is not None and entry.get("base_url") != base_url.rstrip("/"):
            return []
        models = entry.get("models", [])
        _validate_model_list(models)
        return list(models)
    except (OSError, ValueError, TypeError):
        if path.exists():
            _quarantine_cache(path)
        return []


def _quarantine_cache(path: Path) -> None:
    """Move a malformed cache aside without printing its contents."""
    try:
        target = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        os.replace(path, target)
        sys.stderr.write("Warning: malformed model cache was quarantined; treating it as empty.\n")
    except OSError:
        # A cache is advisory. If it cannot be moved, callers still get a
        # cache miss and analysis remains offline-safe.
        pass


def _validate_model_list(models: object) -> None:
    if not isinstance(models, list) or len(models) > MAX_CACHED_MODELS:
        raise ValueError("models must be a bounded list of strings")
    for model in models:
        if not isinstance(model, str) or not model.strip() or len(model) > MAX_MODEL_ID_CHARS:
            raise ValueError("model IDs must be non-empty and bounded strings")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in model):
            raise ValueError("model IDs must not contain control characters")
