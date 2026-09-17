import json


def test_custom_provider_registry_roundtrip(tmp_path):
    from hound.providers import load_custom_providers, remove_custom_provider, save_custom_provider

    path = tmp_path / "providers.yml"
    save_custom_provider("team-router", {"name": "Team", "base_url": "https://models.example/v1", "models": ["b", "a"]}, path)
    assert load_custom_providers(path)["team-router"]["models"] == ["a", "b"]
    remove_custom_provider("team-router", path)
    assert load_custom_providers(path) == {}


def test_anthropic_compatible_provider_roundtrip(tmp_path):
    from hound.providers import load_custom_providers, save_custom_provider

    path = tmp_path / "providers.yml"
    save_custom_provider("claude-gateway", {
        "name": "Claude Gateway",
        "base_url": "https://claude.example/v1",
        "default_model": "claude-sonnet",
        "protocol": "anthropic",
    }, path)
    provider = load_custom_providers(path)["claude-gateway"]
    assert provider["protocol"] == "anthropic"
    assert provider["supports_model_discovery"] is False


def test_anthropic_compatible_check_uses_native_messages_endpoint(monkeypatch):
    from hound.providers import check_anthropic_compatible

    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_request(request, timeout):
        captured.update(url=request.full_url, headers=dict(request.headers), body=json.loads(request.data), timeout=timeout)
        return Response()

    monkeypatch.setattr("hound.providers.urlopen", open_request)
    check_anthropic_compatible("https://claude.example/v1", "secret", "claude-sonnet")
    assert captured["url"] == "https://claude.example/v1/messages"
    assert captured["body"]["model"] == "claude-sonnet"
    assert captured["headers"]["X-api-key"] == "secret"


def test_provider_rejects_insecure_remote_url(tmp_path):
    import pytest
    from hound.providers import save_custom_provider

    with pytest.raises(ValueError, match="HTTPS"):
        save_custom_provider("bad", {"base_url": "http://example.com/v1"}, tmp_path / "providers.yml")


def test_model_discovery_openai_shape(monkeypatch):
    from hound.providers import discover_models

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit): return json.dumps({"data": [{"id": "z"}, {"id": "a"}, {"id": "a"}]}).encode()

    monkeypatch.setattr("hound.providers.urlopen", lambda request, timeout: Response())
    assert discover_models("http://127.0.0.1:20128/v1", "secret") == ["a", "z"]


def test_authenticated_model_discovery_disables_redirects():
    from hound.providers import _NoRedirect

    assert _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example/models") is None


def test_auto_model_uses_first_discovered_catalog_entry(monkeypatch):
    from hound.config import PROVIDERS, resolve_model_name

    monkeypatch.setattr("hound.providers.cached_models", lambda *_args, **_kwargs: ["other", "newly-added-model"])
    assert "default_model" not in PROVIDERS["openai"]
    assert resolve_model_name("openai", "auto") == "other"


def test_auto_model_uses_discovered_model_when_default_is_unavailable(monkeypatch):
    from hound.config import resolve_model_name

    monkeypatch.setattr("hound.providers.cached_models", lambda *_args, **_kwargs: ["available-a", "available-b"])
    assert resolve_model_name("openai", "auto") == "available-a"


def test_manual_model_is_not_rewritten(monkeypatch):
    from hound.config import resolve_model_name

    monkeypatch.setattr("hound.providers.cached_models", lambda *_args, **_kwargs: ["other"])
    assert resolve_model_name("openai", "my-model") == "my-model"
