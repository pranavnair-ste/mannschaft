"""Unit tests for pi_harness.clawteam_profile."""

from __future__ import annotations

import tomllib

import pytest


@pytest.fixture
def cfg(monkeypatch):
    """Build a Config from a known env."""
    from pi_harness.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "sk-profile-test")
    monkeypatch.setenv("PI_HARNESS_REASONING_MODEL", "gpt-5")
    monkeypatch.setenv("PI_HARNESS_FAST_MODEL", "gpt-5-mini")
    return load_config(env_file=None)


def test_build_profile_specs_returns_two_specs(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    specs = build_profile_specs(cfg)

    assert len(specs) == 2
    names = {s.name for s in specs}
    assert names == {"pi-openai-reasoning", "pi-openai-fast"}


def test_reasoning_spec_pins_reasoning_model(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    specs = {s.name: s for s in build_profile_specs(cfg)}

    reasoning = specs["pi-openai-reasoning"]
    assert reasoning.model == "gpt-5"
    assert reasoning.api_key_env == "OPENAI_API_KEY"
    assert reasoning.tier == "reasoning"


def test_fast_spec_pins_fast_model(cfg):
    from pi_harness.clawteam_profile import build_profile_specs

    specs = {s.name: s for s in build_profile_specs(cfg)}

    fast = specs["pi-openai-fast"]
    assert fast.model == "gpt-5-mini"
    assert fast.api_key_env == "OPENAI_API_KEY"
    assert fast.tier == "fast"


def test_spec_to_set_args_emits_clawteam_profile_set_flags(cfg):
    """ProfileSpec.to_set_args returns argv-style flags for `clawteam profile set`."""
    from pi_harness.clawteam_profile import build_profile_specs

    specs = {s.name: s for s in build_profile_specs(cfg)}
    args = specs["pi-openai-reasoning"].to_set_args()

    # The profile name is the first positional arg; the rest are flags.
    assert args[0] == "pi-openai-reasoning"
    assert "--agent" in args
    assert "--model" in args
    assert "gpt-5" in args
    assert "--api-key-env" in args
    assert "OPENAI_API_KEY" in args


def test_profile_doc_toml_is_parseable(cfg):
    """generate_pi_openai_profile returns a TOML string parseable by tomllib."""
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    toml_text = generate_pi_openai_profile(cfg)
    parsed = tomllib.loads(toml_text)

    assert isinstance(parsed, dict)


def test_profile_doc_toml_lists_both_profiles(cfg):
    """The doc TOML must enumerate both profile specs with their model assignments."""
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    parsed = tomllib.loads(generate_pi_openai_profile(cfg))

    assert "profiles" in parsed
    by_name = {p["name"]: p for p in parsed["profiles"]}
    assert by_name["pi-openai-reasoning"]["model"] == "gpt-5"
    assert by_name["pi-openai-fast"]["model"] == "gpt-5-mini"
    assert by_name["pi-openai-reasoning"]["api_key_env"] == "OPENAI_API_KEY"


def test_profile_doc_toml_does_not_embed_secret(cfg):
    """The TOML must reference the env var, never the literal key value."""
    from pi_harness.clawteam_profile import generate_pi_openai_profile

    toml_text = generate_pi_openai_profile(cfg)

    assert "sk-profile-test" not in toml_text


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
    assert target.exists()
    parsed = tomllib.loads(target.read_text())
    assert {p["name"] for p in parsed["profiles"]} == {
        "pi-openai-reasoning",
        "pi-openai-fast",
    }
