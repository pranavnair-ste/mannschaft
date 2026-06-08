"""Unit tests for pi_harness.clawteam_profile."""

from __future__ import annotations

import tomllib

import pytest


@pytest.fixture(autouse=True)
def _local_home(tmp_path, monkeypatch):
    """Isolate HarnessSettings to a temp home so load_settings() returns the
    local defaults (and never reads the developer's real ~/.pi-harness)."""
    monkeypatch.setenv("PI_HARNESS_HOME", str(tmp_path / "home"))
    yield


@pytest.fixture
def cfg(monkeypatch):
    """Build a Config from a known env (retained as the api-fallback key source)."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-profile-test")
    monkeypatch.setenv("PI_HARNESS_REASONING_MODEL", "gpt-5")
    monkeypatch.setenv("PI_HARNESS_FAST_MODEL", "gpt-5-mini")
    return load_config(env_file=None)


LOCAL_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"


def _save_api_settings():
    from pi_harness.settings import BucketConfig, HarnessSettings, save_settings

    save_settings(HarnessSettings(
        orchestrator=BucketConfig(provider="api", model="gpt-5"),
        builder=BucketConfig(provider="api", model="gpt-5-mini"),
    ))


def test_build_profile_specs_returns_two_specs(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    specs = build_profile_specs(cfg)
    assert len(specs) == 2
    assert {s.name for s in specs} == {"pi-openai-reasoning", "pi-openai-fast"}


def test_local_default_profiles_use_pi_agent_and_base_url(cfg):
    """With the local default settings, both profiles run the pi agent against
    the local endpoint with no api key env."""
    from pi_harness.clawteam_profile import build_profile_specs

    specs = {s.name: s for s in build_profile_specs(cfg)}
    for name in ("pi-openai-reasoning", "pi-openai-fast"):
        s = specs[name]
        assert s.agent == "pi"
        assert s.model == LOCAL_MODEL
        assert s.api_key_env is None
        assert s.base_url == "http://localhost:8080/v1"
    assert specs["pi-openai-reasoning"].tier == "reasoning"
    assert specs["pi-openai-fast"].tier == "fast"


def test_api_bucket_profile_keeps_key_env(cfg):
    """An explicitly-selected api bucket carries the OPENAI_API_KEY env source
    and no base_url (cloud fallback)."""
    from pi_harness.clawteam_profile import build_profile_specs

    _save_api_settings()
    specs = {s.name: s for s in build_profile_specs(cfg)}
    reasoning = specs["pi-openai-reasoning"]
    assert reasoning.agent == "pi"
    assert reasoning.model == "gpt-5"
    assert reasoning.api_key_env == "OPENAI_API_KEY"
    assert reasoning.base_url is None


def test_local_spec_to_set_args_emits_base_url_no_key(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    specs = {s.name: s for s in build_profile_specs(cfg)}
    args = specs["pi-openai-reasoning"].to_set_args()

    assert args[0] == "pi-openai-reasoning"
    assert "--agent" in args and "pi" in args
    assert "--model" in args and LOCAL_MODEL in args
    assert "--base-url" in args and "http://localhost:8080/v1" in args
    assert "--api-key-env" not in args  # local needs no key


def test_api_spec_to_set_args_emits_key_env(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    _save_api_settings()
    specs = {s.name: s for s in build_profile_specs(cfg)}
    args = specs["pi-openai-reasoning"].to_set_args()

    assert "--api-key-env" in args and "OPENAI_API_KEY" in args
    assert "--base-url" not in args


def test_profile_doc_toml_is_parseable(cfg):
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    parsed = tomllib.loads(generate_pi_openai_profile(cfg))
    assert isinstance(parsed, dict)


def test_profile_doc_toml_lists_both_profiles_local(cfg):
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    parsed = tomllib.loads(generate_pi_openai_profile(cfg))
    by_name = {p["name"]: p for p in parsed["profiles"]}
    assert by_name["pi-openai-reasoning"]["model"] == LOCAL_MODEL
    assert by_name["pi-openai-fast"]["model"] == LOCAL_MODEL
    assert by_name["pi-openai-reasoning"]["agent"] == "pi"
    assert "api_key_env" not in by_name["pi-openai-reasoning"]  # local: no key env


def test_profile_doc_toml_does_not_embed_secret(cfg):
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    assert "sk-profile-test" not in generate_pi_openai_profile(cfg)


def test_role_mapping_maps_reasoning_to_orchestrator_and_reviewer(cfg):
    from pi_harness.clawteam_profile import ROLE_PROFILE_MAP

    assert ROLE_PROFILE_MAP["orchestrator"] == "pi-openai-reasoning"
    assert ROLE_PROFILE_MAP["reviewer"] == "pi-openai-reasoning"


def test_role_mapping_maps_fast_to_builder_and_scout(cfg):
    from pi_harness.clawteam_profile import ROLE_PROFILE_MAP

    assert ROLE_PROFILE_MAP["builder"] == "pi-openai-fast"
    assert ROLE_PROFILE_MAP["scout"] == "pi-openai-fast"


def test_write_pi_openai_profile_writes_to_disk(cfg, tmp_path):
    from pi_harness.clawteam_profile import write_pi_openai_profile

    target = tmp_path / "pi-openai.toml"
    written = write_pi_openai_profile(cfg, target)
    assert written == target
    parsed = tomllib.loads(target.read_text())
    assert {p["name"] for p in parsed["profiles"]} == {
        "pi-openai-reasoning",
        "pi-openai-fast",
    }
