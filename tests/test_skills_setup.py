# tests/test_skills_setup.py
from __future__ import annotations

from pathlib import Path


def test_repo_skills_dir_points_at_repo_skills():
    from pi_harness.skills_setup import repo_skills_dir
    d = repo_skills_dir()
    assert d.name == "skills"
    assert (d / "pi-harness").exists()  # the dispatch skill lives here


def test_retire_noop_when_absent(tmp_path, capsys):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    root.mkdir()
    assert retire_raw_clawteam_skill(skills_root=root) is None
    assert "clawteam" not in capsys.readouterr().out


def test_retire_moves_aside_reversibly(tmp_path, capsys):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    (root / "clawteam").mkdir(parents=True)
    (root / "clawteam" / "SKILL.md").write_text("raw clawteam skill")

    backup = retire_raw_clawteam_skill(skills_root=root)

    assert backup is not None
    assert not (root / "clawteam").exists()           # original gone
    assert backup.exists()                             # content preserved
    assert (backup / "SKILL.md").read_text() == "raw clawteam skill"
    assert "clawteam" in capsys.readouterr().out        # logged


def test_retire_is_idempotent_with_suffix(tmp_path):
    from pi_harness.skills_setup import retire_raw_clawteam_skill
    root = tmp_path / "skills"
    # first disable
    (root / "clawteam").mkdir(parents=True)
    first = retire_raw_clawteam_skill(skills_root=root)
    assert first.name == "clawteam.disabled"
    # skill reinstalled, disable again -> new non-clobbering backup
    (root / "clawteam").mkdir()
    second = retire_raw_clawteam_skill(skills_root=root)
    assert second is not None and second != first and second.exists()
    assert first.exists()  # earlier backup untouched
