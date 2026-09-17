import json

import pytest

from hound import subscription_auth
from hound.config import load_config


def test_risk_acceptance_roundtrip(tmp_path):
    path = tmp_path / "consent.json"
    assert not subscription_auth.risk_accepted("openai-oauth", path)
    subscription_auth.accept_risk("openai-oauth", path)
    assert subscription_auth.risk_accepted("openai-oauth", path)
    assert json.loads(path.read_text(encoding="utf-8"))["accepted"] == ["openai-oauth"]


def test_subscription_provider_enables_llm_without_api_key(monkeypatch):
    monkeypatch.delenv("HOUND_API_KEY", raising=False)
    config = load_config(provider="claude-oauth", model="sonnet")
    assert config.llm_enabled is True
    assert config.api_key == ""


def test_invoke_requires_explicit_consent(monkeypatch, tmp_path):
    monkeypatch.setattr(subscription_auth, "CONSENT_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(subscription_auth.shutil, "which", lambda _name: "provider-cli")
    with pytest.raises(RuntimeError, match="risk notice not accepted"):
        subscription_auth.invoke("gemini-oauth", "auto", "prompt", {}, 1)
