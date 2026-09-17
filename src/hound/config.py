"""Configuration: environment variables + optional YAML file."""
from __future__ import annotations

import os
import sys
from difflib import get_close_matches
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from hound.fsio import atomic_write, read_bounded_text
from hound.models import KINDS
from hound.pathutil import path_has_symlink
from hound.trust import policy_for, resolve_source_class
from hound.urlutil import validate_http_url

DEFAULT_MODEL = "auto"
DEFAULT_CONFIG_PATH = Path(".hound.yml")
MAX_CONFIG_BYTES = 2 * 1024 * 1024

CONFIG_SCHEMA: dict[str, object] = {
    "llm": {
        "provider", "model", "base_url", "api_key", "temperature", "timeout",
        "max_tokens", "max_retries", "max_concurrency", "routing", "skip_kinds",
        "require", "pricing",
    },
    "trust": {"source_class"},
    "redact": None,
    "components": "*",
    "dedup": {
        "path", "state_file", "backend", "url", "token", "max_entries",
        "retention_days", "reuse", "reuse_after_occurrences",
    },
    "policy": {"severity_overrides", "recurrence_threshold"},
    "github": {"repo", "api_base"},
    "jira": {"url", "project", "token", "email"},
    "gitlab": {"url", "project", "token"},
    "slack": {"webhook_url"},
    "observability": {
        "prometheus_url", "prometheus_token", "tempo_url", "tempo_token", "window_minutes",
    },
    "runbooks": "*",
    "source": {"send_to_llm"},
}


def env_value(canonical: str, legacy: str | None = None) -> str | None:
    """Read a canonical environment variable with a deprecated fallback."""
    if canonical in os.environ:
        return os.environ.get(canonical)
    if legacy and legacy in os.environ:
        sys.stderr.write(f"Warning: {legacy} is deprecated; use {canonical}.\n")
        return os.environ.get(legacy)
    return None


def _validate_unknown_keys(config: dict, *, strict: bool) -> list[str]:
    unknown: list[str] = []
    for key, value in config.items():
        if key not in CONFIG_SCHEMA:
            suggestion = get_close_matches(str(key), CONFIG_SCHEMA, n=1)
            suffix = f"; did you mean {suggestion[0]!r}?" if suggestion else ""
            unknown.append(f"unknown config key {key!r}{suffix}")
            continue
        allowed = CONFIG_SCHEMA[key]
        if not isinstance(value, dict) or not isinstance(allowed, set):
            continue
        for child in value:
            if child in allowed:
                continue
            suggestion = get_close_matches(str(child), sorted(allowed), n=1)
            suffix = f"; did you mean {key}.{suggestion[0]}?" if suggestion else ""
            unknown.append(f"unknown config key {key}.{child}{suffix}")
    if unknown and strict:
        raise ValueError("; ".join(unknown))
    for warning in unknown:
        sys.stderr.write(f"Warning: {warning}\n")
    return unknown


def _mapping_section(config: dict, name: str) -> dict:
    value = config.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config {name} section must be a mapping")
    return value


def _configured_string(mapping: dict, key: str, label: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _validate_http_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return validate_http_url(value, label=label)


def _validate_delivery_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return validate_http_url(value, label=label, require_https=True, allow_loopback_http=False)

#: Known provider presets (all OpenAI-compatible). Key = name users pass in
#: HOUND_API_PROVIDER (or `llm.provider` in YAML). `env` = env var names that
#: override the preset when set; `default` = fallback when nothing is set.
PROVIDERS: dict[str, dict] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "supports_model_discovery": True,
        "env": {"api_key": "OPENAI_API_KEY", "model": "OPENAI_MODEL", "base_url": "OPENAI_BASE_URL"},
    },
    # Note: Anthropic's native API is not OpenAI-compatible. This preset only
    # works when ANTHROPIC_BASE_URL points at an OpenAI-compatible proxy in
    # front of Anthropic (or a gateway that translates the protocol).
    "anthropic": {
        "base_url": None,
        "supports_model_discovery": False,
        "env": {"api_key": "ANTHROPIC_API_KEY", "model": "ANTHROPIC_MODEL", "base_url": "ANTHROPIC_BASE_URL"},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "supports_model_discovery": True,
        "env": {"api_key": "GEMINI_API_KEY", "model": "GEMINI_MODEL", "base_url": "GEMINI_BASE_URL"},
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "supports_model_discovery": True,
        "env": {"api_key": "GROQ_API_KEY", "model": "GROQ_MODEL", "base_url": "GROQ_BASE_URL"},
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "supports_model_discovery": True,
        "env": {"model": "OLLAMA_MODEL", "base_url": "OLLAMA_BASE_URL"},
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "supports_model_discovery": True,
        "env": {"api_key": "DEEPSEEK_API_KEY", "model": "DEEPSEEK_MODEL", "base_url": "DEEPSEEK_BASE_URL"},
    },
    "9router": {
        "base_url": "http://127.0.0.1:20128/v1",
        "supports_model_discovery": True,
        "env": {"api_key": "NINE_ROUTER_API_KEY", "model": "NINE_ROUTER_MODEL", "base_url": "NINE_ROUTER_BASE_URL"},
    },
    "openai-oauth": {
        "base_url": None, "default_model": "auto", "supports_model_discovery": False,
        "env": {"model": "OPENAI_OAUTH_MODEL"},
    },
    "claude-oauth": {
        "base_url": None, "default_model": "auto", "supports_model_discovery": False,
        "env": {"model": "CLAUDE_OAUTH_MODEL"},
    },
    "gemini-oauth": {
        "base_url": None, "default_model": "auto", "supports_model_discovery": False,
        "env": {"model": "GEMINI_OAUTH_MODEL"},
    },
    "azure": {
        "base_url": None,  # Azure needs a custom base URL, always
        "supports_model_discovery": False,
        "env": {"api_key": "AZURE_OPENAI_API_KEY", "model": "AZURE_OPENAI_MODEL", "base_url": "AZURE_OPENAI_BASE_URL"},
    },
    "custom": {
        "base_url": None,
        "supports_model_discovery": True,
        "env": {"api_key": "CUSTOM_API_KEY", "model": "CUSTOM_MODEL", "base_url": "CUSTOM_BASE_URL"},
    },
}


def _pick_provider(provider: str | None) -> str:
    if not provider:
        p = (env_value("HOUND_API_PROVIDER", "TH_API_PROVIDER") or "openai").strip().lower()
    else:
        p = provider.strip().lower()

    if p not in _effective_providers():
        raise ValueError(f"unknown provider: {p}")
    return p


def _effective_providers() -> dict[str, dict]:
    from hound.providers import load_custom_providers

    providers = dict(PROVIDERS)
    for provider_id, definition in load_custom_providers().items():
        if provider_id not in providers:
            providers[provider_id] = {
                "base_url": definition.get("base_url"),
                "default_model": definition.get("default_model", ""),
                "models": definition.get("models", []),
                "supports_model_discovery": definition.get("supports_model_discovery", True),
                "protocol": definition.get("protocol", "openai"),
                "env": {},
            }
    return providers


def resolve_model_name(provider: str, model: str, *, base_url: str | None = None) -> str:
    """Resolve ``auto`` from a user-managed or discovered provider catalog.

    Analysis stays cache-only: it never sends a surprise discovery request.
    Built-in providers deliberately have no hard-coded model. A custom
    provider may define a user-owned preferred model, otherwise the first
    cached catalog entry is selected deterministically.
    """
    if model.strip().lower() != "auto":
        return model

    from hound.providers import cached_models

    preset = _effective_providers()[provider]
    default = str(preset.get("default_model") or "").strip()
    configured = [str(value) for value in preset.get("models", []) if str(value).strip()]
    if preset.get("supports_model_discovery") is False:
        if default:
            return default
        if configured:
            return configured[0]
        raise ValueError(
            f"provider {provider!r} does not support model discovery; "
            "select a model/deployment explicitly"
        )
    discovered = cached_models(provider, base_url=base_url)
    available = list(dict.fromkeys([*configured, *discovered]))
    if default:
        return default
    if available:
        return available[0]
    raise ValueError(
        f"provider {provider!r} has no cached model catalog; "
        "discover models or select one explicitly with --model"
    )


def _env(name: str | None) -> str | None:
    if not name:
        return None
    return os.environ.get(name) or None


@dataclass
class Config:
    api_key: str = ""
    base_url: str | None = None
    model: str = DEFAULT_MODEL
    provider: str = "openai"
    temperature: float = 0.2
    timeout: float = 120.0
    max_tokens: int = 2048
    max_retries: int = 3
    max_concurrency: int = 4
    offline: bool = False
    request_account: object | None = field(default=None, repr=False, compare=False)
    redact: bool = True
    components: dict[str, str] = field(default_factory=dict)
    state_file: str | None = None
    state_backend: str = "file"
    state_url: str = ""
    state_token: str = ""
    dedup_max_entries: int = 50000
    dedup_retention_days: int = 90
    gh_token: str = ""
    gh_repo: str = ""
    gh_api_base: str = "https://api.github.com"
    jira_url: str = ""
    jira_project: str = ""
    jira_token: str = ""
    jira_email: str = ""
    gitlab_url: str = ""
    gitlab_project: str = ""
    gitlab_token: str = ""
    slack_webhook: str = ""
    severity_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    recurrence_threshold: int = 3
    # Cost control (M19.4): reuse past analyses instead of re-calling the LLM,
    # skip the LLM for cheap kinds, and cap spending.
    reuse: bool = True
    reuse_after_occurrences: int = 3
    routing: str = "all"
    skip_kinds: list[str] = field(default_factory=list)
    pricing: dict[str, dict] = field(default_factory=dict)
    require_llm: bool = False
    source_class: str = "local_artifact"
    allow_source_context: bool = True
    allow_enrichment: bool = True
    allow_llm: bool = True
    allow_delivery: bool = True
    prometheus_url: str = ""
    prometheus_token: str = ""
    tempo_url: str = ""
    tempo_token: str = ""
    observability_window_minutes: int = 15
    runbooks: dict[str, str] = field(default_factory=dict)
    source_send_to_llm: bool = False

    @property
    def llm_enabled(self) -> bool:
        if self.offline or not self.allow_llm:
            return False
        if self.provider in {"openai-oauth", "claude-oauth", "gemini-oauth"}:
            return True
        if self.api_key:
            return True
        if not self.base_url:
            return False
        return (urlsplit(self.base_url).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def load_config(
    offline: bool = False,
    config_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    redact: bool | None = None,
    max_retries: int | None = None,
    require_llm: bool | None = None,
    source_class: str | None = None,
    strict: bool = False,
) -> Config:
    yaml_cfg: dict = {}
    if config_path:
        config_file = Path(config_path).expanduser()
        if path_has_symlink(config_file) or config_file.is_symlink():
            raise ValueError("config path must not contain symlinked path components")
        try:
            if config_file.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("config exceeds the 2 MiB limit")
            raw_text = read_bounded_text(config_file, MAX_CONFIG_BYTES, encoding="utf-8")
            parsed = yaml.safe_load(raw_text)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"could not read config {config_path}: {exc}") from exc
        if isinstance(parsed, dict):
            yaml_cfg = parsed
        elif parsed is not None:
            raise ValueError("config root must be a mapping")
    _validate_unknown_keys(yaml_cfg, strict=strict)

    llm_cfg = _mapping_section(yaml_cfg, "llm")
    for key in ("provider", "model", "base_url", "api_key"):
        _configured_string(llm_cfg, key, f"llm.{key}")
    trust_cfg = _mapping_section(yaml_cfg, "trust")
    configured_source = trust_cfg.get("source_class")
    if configured_source is not None and not isinstance(configured_source, str):
        raise ValueError("trust.source_class must be a string")
    trust = policy_for(resolve_source_class(source_class, configured_source))
    effective_offline = offline or not trust.allow_llm

    # 1) Provider selection: CLI flag > YAML > HOUND_API_PROVIDER > "openai"
    prov_input = provider or llm_cfg.get("provider")
    provider = _pick_provider(str(prov_input) if prov_input else None)
    preset = _effective_providers()[provider]
    env = preset.get("env", {})

    # 2) Precedence ladder: CLI > YAML > HOUND_* > Provider env > auto.
    p_key_env = env.get("api_key")
    yaml_key = llm_cfg.get("api_key")
    if yaml_key:
        sys.stderr.write(
            "Warning: api_key found in YAML config. Storing secrets in config files risks "
            "leaking them via version control; prefer environment variables.\n"
        )
    api_key = (
        api_key
        or yaml_key
        or env_value("HOUND_API_KEY", "TH_API_KEY")
        or _env(p_key_env)
        or __import__("hound.credentials", fromlist=["get_api_key"]).get_api_key(provider)
        or ""
    )

    p_url_env = env.get("base_url")
    base_url = (
        base_url
        or llm_cfg.get("base_url")
        or env_value("HOUND_BASE_URL", "TH_BASE_URL")
        or _env(p_url_env)
        or preset.get("base_url")
    )

    p_model_env = env.get("model")
    model = (
        model
        or llm_cfg.get("model")
        or env_value("HOUND_MODEL", "TH_MODEL")
        or _env(p_model_env)
        or preset.get("default_model")
        or DEFAULT_MODEL
    )

    # 3) Legacy OPENAI_* fallback applies ONLY to the openai preset
    if provider == "openai":
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")

        # In case base_url wasn't customized via HOUND_LLM_BASE_URL, check OPENAI_BASE_URL
        if not os.environ.get("HOUND_LLM_BASE_URL") and not llm_cfg.get("base_url"):
            legacy_url = os.environ.get("OPENAI_BASE_URL")
            if legacy_url:
                base_url = legacy_url

    if not str(model).strip():
        raise ValueError("model must not be empty")
    if provider == "anthropic" and not effective_offline and not base_url:
        raise ValueError("anthropic requires ANTHROPIC_BASE_URL pointing to an OpenAI-compatible proxy")
    if provider in {"azure", "custom"} and not effective_offline and not base_url:
        raise ValueError(f"{provider} requires an OpenAI-compatible HTTPS base_url")
    if not effective_offline:
        if base_url:
            _validate_http_url(base_url, "base_url")
    elif base_url:
        # In offline mode, userinfo must always be rejected even if offline,
        # but ambient remote base URLs from environment are tolerated unless strict.
        parsed_ambient = urlsplit(base_url)
        if parsed_ambient.username is not None or parsed_ambient.password is not None:
            raise ValueError("base_url must not include URL credentials")
        if strict:
            _validate_http_url(base_url, "base_url")
        else:
            try:
                _validate_http_url(base_url, "base_url")
            except ValueError as exc:
                if "URL credentials" in str(exc):
                    raise

    temp_val = llm_cfg.get("temperature", 0.2)
    timeout_val = llm_cfg.get("timeout", 120.0)
    tokens_val = llm_cfg.get("max_tokens", 2048)
    retries_val = llm_cfg.get("max_retries", 3)
    concurrency_val = llm_cfg.get("max_concurrency", 4)

    try:
        temperature = float(temp_val if effective_offline else (env_value("HOUND_TEMPERATURE", "TH_TEMPERATURE") or temp_val))
        timeout = float(timeout_val if effective_offline else (env_value("HOUND_TIMEOUT", "TH_TIMEOUT") or timeout_val))
        max_tokens = int(tokens_val if effective_offline else (env_value("HOUND_MAX_TOKENS", "TH_MAX_TOKENS") or tokens_val))
        retry_source = max_retries if max_retries is not None else (retries_val if effective_offline else (env_value("HOUND_MAX_RETRIES", "TH_MAX_RETRIES") or retries_val))
        resolved_retries = int(retry_source)
        concurrency_source = concurrency_val if effective_offline else (env_value("HOUND_MAX_CONCURRENCY", "TH_MAX_CONCURRENCY") or concurrency_val)
        resolved_concurrency = int(concurrency_source)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid LLM numeric configuration: {exc}") from exc

    # 4) Validate numeric knobs early with descriptive errors instead of
    #    cryptic failures at request time.
    if not 0.0 <= temperature <= 2.0:
        raise ValueError(f"temperature must be in [0.0, 2.0], got {temperature!r}")
    if not 0 < timeout <= 600:
        raise ValueError(f"timeout must be in (0, 600], got {timeout!r}")
    if not 0 < max_tokens <= 32768:
        raise ValueError(f"max_tokens must be in (0, 32768], got {max_tokens!r}")
    if not 0 <= resolved_retries <= 10:
        raise ValueError(f"max_retries must be in [0, 10], got {resolved_retries!r}")
    if not 1 <= resolved_concurrency <= 64:
        raise ValueError(f"max_concurrency must be in [1, 64], got {resolved_concurrency!r}")

    routing_val = llm_cfg.get("routing", "all")
    if routing_val not in {"all", "exclude-kinds"}:
        raise ValueError(f"llm.routing must be 'all' or 'exclude-kinds', got {routing_val!r}")
    routing = str(routing_val)

    skip_val = llm_cfg.get("skip_kinds") or []
    if not isinstance(skip_val, list) or not all(isinstance(kind, str) for kind in skip_val):
        raise ValueError("llm.skip_kinds must be a list of failure kind names")
    unknown_kinds = sorted(set(skip_val) - set(KINDS))
    if unknown_kinds:
        raise ValueError(f"llm.skip_kinds contains unknown kinds: {', '.join(unknown_kinds)}")
    skip_kinds = [str(kind) for kind in skip_val]

    require_llm_val = llm_cfg.get("require", False)
    if not isinstance(require_llm_val, bool):
        raise ValueError("llm.require must be a boolean")
    resolved_require_llm = require_llm if require_llm is not None else (
        require_llm_val or env_value("HOUND_REQUIRE_LLM", "TH_REQUIRE_LLM") == "1"
    )
    if effective_offline and resolved_require_llm:
        raise ValueError("llm.require cannot be enabled in offline mode")
    if not trust.allow_llm and resolved_require_llm:
        raise ValueError(f"llm.require is forbidden for source class {trust.source_class}")

    pricing_val = llm_cfg.get("pricing") or {}
    if not isinstance(pricing_val, dict):
        raise ValueError("llm.pricing must be a mapping of provider:model to rates")
    pricing: dict[str, dict] = {}
    for name, entry in pricing_val.items():
        if not isinstance(entry, dict):
            raise ValueError(f"llm.pricing.{name} must be a mapping")
        try:
            prompt_per = float(entry.get("prompt_per_mtok", 0.0) or 0.0)
            completion_per = float(entry.get("completion_per_mtok", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"llm.pricing.{name} rates must be numbers") from exc
        if prompt_per < 0 or completion_per < 0:
            raise ValueError(f"llm.pricing.{name} rates must be >= 0")
        pricing[str(name)] = {"prompt_per_mtok": prompt_per, "completion_per_mtok": completion_per}


    redact_cfg = yaml_cfg.get("redact")
    if redact_cfg is not None and not isinstance(redact_cfg, bool):
        raise ValueError("redact must be a boolean")
    redact_val = not (env_value("HOUND_ALLOW_UNREDACTED", "TH_NO_REDACT") == "1") and redact_cfg is not False
    if redact is not None:
        redact_val = redact
    if trust.source_class == "fork_pr":
        redact_val = True
    redact = redact_val

    cfg = Config(
        api_key=str(api_key),
        base_url=str(base_url) if base_url else None,
        model=str(model),
        provider=provider,
        temperature=temperature,
        timeout=timeout,
        max_tokens=max_tokens,
        max_retries=resolved_retries,
        max_concurrency=resolved_concurrency,
        offline=effective_offline,
        redact=redact,
        routing=routing,
        skip_kinds=skip_kinds,
        pricing=pricing,
        require_llm=resolved_require_llm,
        source_class=trust.source_class,
        allow_source_context=trust.allow_source_context,
        allow_enrichment=trust.allow_enrichment,
        allow_llm=trust.allow_llm,
        allow_delivery=trust.allow_delivery,
        gh_token=os.environ.get("GH_TOKEN", ""),
        gh_repo=os.environ.get("GH_REPO", ""),
        gh_api_base=os.environ.get("GH_API_BASE", "https://api.github.com"),
    )

    comps = _mapping_section(yaml_cfg, "components")
    cfg.components = {str(k): str(v) for k, v in comps.items()}

    dedup_cfg = _mapping_section(yaml_cfg, "dedup")
    state = dedup_cfg.get("path") or dedup_cfg.get("state_file")
    if state:
        cfg.state_file = str(state)
    backend = dedup_cfg.get("backend")
    if backend:
        cfg.state_backend = str(backend)
    url = _configured_string(dedup_cfg, "url", "dedup.url")
    if url:
        cfg.state_url = _validate_http_url(url, "dedup.url")
    token = dedup_cfg.get("token")
    if token:
        sys.stderr.write("Warning: dedup token found in YAML config; prefer an environment variable.\n")
        cfg.state_token = str(token)
    entries = dedup_cfg.get("max_entries")
    if entries is not None:
        try:
            cfg.dedup_max_entries = int(entries)
        except (TypeError, ValueError) as exc:
            raise ValueError("dedup.max_entries must be an integer") from exc
        if cfg.dedup_max_entries < 1:
            raise ValueError("dedup.max_entries must be >= 1")
    retention = dedup_cfg.get("retention_days")
    if retention is not None:
        try:
            cfg.dedup_retention_days = int(retention)
        except (TypeError, ValueError) as exc:
            raise ValueError("dedup.retention_days must be an integer") from exc
        if cfg.dedup_retention_days < 1:
            raise ValueError("dedup.retention_days must be >= 1")
    if cfg.state_backend not in {"", "file", "sqlite"}:
        if cfg.state_backend == "http":
            raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")
        raise ValueError(f"unsupported dedup backend: {cfg.state_backend!r}")

    reuse_val = dedup_cfg.get("reuse", True)
    if not isinstance(reuse_val, bool):
        raise ValueError("dedup.reuse must be a boolean")
    cfg.reuse = reuse_val
    occurrences_val = dedup_cfg.get("reuse_after_occurrences", 3)
    try:
        cfg.reuse_after_occurrences = int(occurrences_val)
    except (TypeError, ValueError) as exc:
        raise ValueError("dedup.reuse_after_occurrences must be an integer") from exc
    if not 2 <= cfg.reuse_after_occurrences <= 1000:
        raise ValueError("dedup.reuse_after_occurrences must be in [2, 1000]")

    policy = _mapping_section(yaml_cfg, "policy")
    overrides = _mapping_section(policy, "severity_overrides")
    cfg.severity_overrides = {
        str(environment): {str(kind): str(severity) for kind, severity in values.items()}
        for environment, values in overrides.items() if isinstance(values, dict)
    }
    threshold = policy.get("recurrence_threshold", 3)
    try:
        cfg.recurrence_threshold = int(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("policy.recurrence_threshold must be an integer") from exc
    if not 2 <= cfg.recurrence_threshold <= 100:
        raise ValueError("policy.recurrence_threshold must be in [2, 100]")

    gh = _mapping_section(yaml_cfg, "github")
    if gh.get("repo"):
        cfg.gh_repo = str(gh["repo"])
    gh_api_base = _configured_string(gh, "api_base", "github.api_base")
    if gh_api_base:
        cfg.gh_api_base = _validate_http_url(gh_api_base, "github.api_base")
    elif not effective_offline and cfg.gh_api_base:
        cfg.gh_api_base = _validate_http_url(cfg.gh_api_base, "github.api_base")

    jira = _mapping_section(yaml_cfg, "jira")
    jira_url = _configured_string(jira, "url", "jira.url")
    if jira_url:
        cfg.jira_url = _validate_delivery_url(jira_url, "jira.url")
    if jira.get("project"):
        cfg.jira_project = str(jira["project"])
    if jira.get("token"):
        sys.stderr.write("Warning: Jira token found in YAML config; prefer an environment variable.\n")
        cfg.jira_token = str(jira["token"])
    if jira.get("email"):
        cfg.jira_email = str(jira["email"])
    jira_env = os.environ.get("JIRA_TOKEN") or os.environ.get("JIRA_API_TOKEN")
    if jira_env and not cfg.jira_token:
        cfg.jira_token = jira_env
    if os.environ.get("JIRA_URL") and not cfg.jira_url:
        cfg.jira_url = os.environ.get("JIRA_URL", "")
    if cfg.jira_url and not effective_offline:
        cfg.jira_url = _validate_delivery_url(cfg.jira_url, "jira.url")
    if os.environ.get("JIRA_PROJECT") and not cfg.jira_project:
        cfg.jira_project = os.environ.get("JIRA_PROJECT", "")
    if os.environ.get("JIRA_EMAIL") and not cfg.jira_email:
        cfg.jira_email = os.environ.get("JIRA_EMAIL", "")

    gitlab = _mapping_section(yaml_cfg, "gitlab")
    gitlab_url = _configured_string(gitlab, "url", "gitlab.url")
    if gitlab_url:
        cfg.gitlab_url = _validate_delivery_url(gitlab_url, "gitlab.url")
    if gitlab.get("project"):
        cfg.gitlab_project = str(gitlab["project"])
    if gitlab.get("token"):
        sys.stderr.write("Warning: GitLab token found in YAML config; prefer an environment variable.\n")
        cfg.gitlab_token = str(gitlab["token"])
    if os.environ.get("GITLAB_TOKEN") and not cfg.gitlab_token:
        cfg.gitlab_token = os.environ.get("GITLAB_TOKEN", "")
    if os.environ.get("GITLAB_URL") and not cfg.gitlab_url:
        cfg.gitlab_url = os.environ.get("GITLAB_URL", "")
    if cfg.gitlab_url and not effective_offline:
        cfg.gitlab_url = _validate_delivery_url(cfg.gitlab_url, "gitlab.url")
    if os.environ.get("GITLAB_PROJECT") and not cfg.gitlab_project:
        cfg.gitlab_project = os.environ.get("GITLAB_PROJECT", "")

    slack = _mapping_section(yaml_cfg, "slack")
    slack_webhook = _configured_string(slack, "webhook_url", "slack.webhook_url")
    if slack_webhook:
        cfg.slack_webhook = _validate_delivery_url(slack_webhook, "slack.webhook_url")
    if os.environ.get("SLACK_WEBHOOK_URL") and not cfg.slack_webhook:
        cfg.slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if cfg.slack_webhook and not effective_offline:
        cfg.slack_webhook = _validate_delivery_url(cfg.slack_webhook, "slack.webhook_url")

    observability = _mapping_section(yaml_cfg, "observability")
    _configured_string(observability, "prometheus_url", "observability.prometheus_url")
    _configured_string(observability, "tempo_url", "observability.tempo_url")
    cfg.prometheus_url = str(observability.get("prometheus_url") or os.environ.get("PROMETHEUS_URL") or "").rstrip("/")
    cfg.tempo_url = str(observability.get("tempo_url") or os.environ.get("TEMPO_URL") or "").rstrip("/")
    for name, value in (("prometheus_url", cfg.prometheus_url), ("tempo_url", cfg.tempo_url)):
        if not value:
            continue
        _validate_http_url(value, f"observability.{name}")
    if observability.get("prometheus_token") or observability.get("tempo_token"):
        sys.stderr.write("Warning: observability token found in YAML config; prefer environment variables.\n")
    cfg.prometheus_token = str(observability.get("prometheus_token") or os.environ.get("PROMETHEUS_TOKEN") or "")
    cfg.tempo_token = str(observability.get("tempo_token") or os.environ.get("TEMPO_TOKEN") or "")
    window = observability.get("window_minutes", 15)
    try:
        cfg.observability_window_minutes = int(window)
    except (TypeError, ValueError) as exc:
        raise ValueError("observability.window_minutes must be an integer") from exc
    if not 1 <= cfg.observability_window_minutes <= 120:
        raise ValueError("observability.window_minutes must be in [1, 120]")
    runbooks = _mapping_section(yaml_cfg, "runbooks")
    cfg.runbooks = {}
    for service, url_value in runbooks.items():
        url = _validate_http_url(url_value, f"runbooks.{service}")
        cfg.runbooks[str(service)] = url
    source = _mapping_section(yaml_cfg, "source")
    send_to_llm = source.get("send_to_llm", False)
    if not isinstance(send_to_llm, bool):
        raise ValueError("source.send_to_llm must be a boolean")
    cfg.source_send_to_llm = send_to_llm
    return cfg


def set_model_config(value: str, config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    """Persist provider or model in existing YAML config using atomic replacement."""
    value = value.strip()
    if not value:
        raise ValueError("provider or model must not be empty")
    path = Path(config_path).expanduser()
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("config path must not contain symlinked path components")
    data: dict = {}
    if path.exists():
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("config exceeds the 2 MiB limit")
        parsed = yaml.safe_load(read_bounded_text(path, MAX_CONFIG_BYTES, encoding="utf-8"))
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError(f"config root must be a mapping: {path}")
        data = parsed or {}
    llm = data.get("llm")
    if llm is not None and not isinstance(llm, dict):
        raise ValueError(f"config llm section must be a mapping: {path}")
    llm = dict(llm or {})
    if value.lower() in _effective_providers():
        provider = value.lower()
        llm["provider"] = provider
        llm["model"] = "auto"
    else:
        llm["model"] = value
    data["llm"] = llm
    path.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(path.parent) or path.is_symlink():
        raise ValueError("config path must not contain symlinked path components")
    atomic_write(path, yaml.safe_dump(data, sort_keys=False))
    return path


def set_llm_config_value(key: str, value: str, config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    """Persist one explicit non-secret LLM setting."""
    if key == "model":
        value = value.strip()
        if not value:
            raise ValueError("model must not be empty")
    elif key == "provider":
        value = _pick_provider(value)
    else:
        raise ValueError(f"unsupported LLM setting: {key}")

    path = Path(config_path).expanduser()
    if path_has_symlink(path) or path.is_symlink():
        raise ValueError("config path must not contain symlinked path components")
    data: dict = {}
    if path.exists():
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("config exceeds the 2 MiB limit")
        parsed = yaml.safe_load(read_bounded_text(path, MAX_CONFIG_BYTES, encoding="utf-8"))
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError(f"config root must be a mapping: {path}")
        data = parsed or {}
    llm = data.get("llm")
    if llm is not None and not isinstance(llm, dict):
        raise ValueError(f"config llm section must be a mapping: {path}")
    llm = dict(llm or {})
    llm[key] = value
    if key == "provider":
        llm["model"] = "auto"
    data["llm"] = llm
    path.parent.mkdir(parents=True, exist_ok=True)
    if path_has_symlink(path.parent) or path.is_symlink():
        raise ValueError("config path must not contain symlinked path components")
    atomic_write(path, yaml.safe_dump(data, sort_keys=False))
    return path
