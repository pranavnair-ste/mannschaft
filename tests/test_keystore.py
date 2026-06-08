"""Tests for the chmod-600 provider key store."""
from __future__ import annotations

import pytest
from dotenv import dotenv_values


@pytest.fixture
def ks(tmp_path, monkeypatch):
    p = tmp_path / "secrets.env"
    monkeypatch.setenv("PI_HARNESS_KEYSTORE_PATH", str(p))
    return p


def test_set_get_has_roundtrip(ks):
    from pi_harness import keystore

    assert keystore.has_key("openai") is False
    keystore.set_key("openai", "sk-abcdEFGH")
    assert keystore.get_key("openai") == "sk-abcdEFGH"
    assert keystore.has_key("openai") is True


def test_file_is_chmod_600(ks):
    from pi_harness import keystore

    keystore.set_key("openai", "sk-abcdEFGH")
    assert oct(ks.stat().st_mode & 0o777) == "0o600"


def test_mask_hides_full_key(ks):
    from pi_harness import keystore

    m = keystore.mask("sk-abcdEFGH")
    assert "sk-abcdEFGH" not in m
    assert m.endswith("EFGH")


def test_set_key_preserves_foreign_lines(ks):
    from pi_harness import keystore

    ks.parent.mkdir(parents=True, exist_ok=True)
    ks.write_text("PI_HARNESS_SMOKE_EXECUTOR=pi\n")
    keystore.set_key("openai", "sk-x")
    vals = dotenv_values(str(ks))
    assert vals.get("PI_HARNESS_SMOKE_EXECUTOR") == "pi"
    assert vals.get("OPENAI_API_KEY") == "sk-x"


def test_keystore_path_honors_env(ks):
    from pi_harness import keystore

    assert keystore.keystore_path() == ks


def test_unknown_provider_raises(ks):
    from pi_harness import keystore

    with pytest.raises(ValueError):
        keystore.set_key("anthropic", "x")
