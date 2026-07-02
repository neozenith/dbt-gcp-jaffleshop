"""Unit tests for `adaf gha init` — the version-stamped composite-action installer (pure; `make ci`)."""

# Standard Library
import argparse
from pathlib import Path

# First Party
from adaf import __version__, config
from adaf.gha import actions


def test_banner_uses_hash_comment_for_code() -> None:
    line = actions.banner("1.2.3", ".yml")
    assert line.startswith("# adaf:managed version=1.2.3")
    assert not line.endswith("-->")


def test_banner_uses_html_comment_for_markdown() -> None:
    line = actions.banner("1.2.3", ".md")
    assert line.startswith("<!-- adaf:managed version=1.2.3")
    assert line.endswith(" -->")


def test_with_header_prepends_for_plain_file() -> None:
    out = actions.with_header("name: ADAF\n", ".yml", "9.9.9")
    assert out.splitlines()[0] == actions.banner("9.9.9", ".yml")
    assert "name: ADAF" in out


def test_with_header_inserts_after_shebang() -> None:
    out = actions.with_header("#!/bin/bash\nset -e\n", ".sh", "9.9.9")
    lines = out.splitlines()
    assert lines[0] == "#!/bin/bash"  # shebang stays line 1 so the script remains executable
    assert lines[1] == actions.banner("9.9.9", ".sh")
    assert lines[2] == "set -e"


def test_managed_version_round_trips() -> None:
    stamped = actions.with_header("description: x\n", ".yml", "4.5.6")
    assert actions.managed_version(stamped) == "4.5.6"


def test_managed_version_none_when_unmanaged() -> None:
    assert actions.managed_version("name: plain\ndescription: y\n") is None


def test_managed_version_ignores_body_version_token() -> None:
    # A `version=` further down the file must NOT be mistaken for the managed banner.
    text = "name: x\n\n\n\n\nrun: echo version=7.7.7\n"
    assert actions.managed_version(text) is None


def _args(actions_dir: Path, workflows_dir: Path, *, force: bool = False) -> argparse.Namespace:
    return argparse.Namespace(color="never", actions_dir=actions_dir, workflows_dir=workflows_dir, force=force)


def _tree(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def test_cmd_init_creates_then_is_idempotent(tmp_path: Path) -> None:
    dest, wf = tmp_path / "actions", tmp_path / "workflows"
    assert actions.cmd_init(_args(dest, wf)) == 0

    # Every packaged asset landed in its own tree, stamped with the current version.
    assert _tree(dest) == _tree(config.GHA_ACTIONS_ASSETS_DIR)
    assert _tree(wf) == _tree(config.GHA_WORKFLOWS_ASSETS_DIR)
    assert (wf / "adaf-reusable.yml").exists()  # the reusable workflow deploys to the workflows dir
    assert (wf / "adaf-cleanup.yml").exists()  # the PR-close cleanup workflow deploys alongside it
    sample = next(iter(_tree(dest)))
    assert actions.managed_version((dest / sample).read_text()) == __version__
    assert actions.managed_version((wf / "adaf-reusable.yml").read_text()) == __version__
    assert actions.managed_version((wf / "adaf-cleanup.yml").read_text()) == __version__

    # A second run with the same version overwrites nothing (all "current") — mtimes unchanged.
    everything = lambda: {p: p.stat().st_mtime_ns for d in (dest, wf) for p in d.rglob("*") if p.is_file()}  # noqa: E731
    before = everything()
    assert actions.cmd_init(_args(dest, wf)) == 0
    assert everything() == before


def test_cmd_init_skips_stale_without_force_then_force_overwrites(tmp_path: Path) -> None:
    dest, wf = tmp_path / "actions", tmp_path / "workflows"
    rel = next(p.relative_to(config.GHA_ACTIONS_ASSETS_DIR) for p in config.GHA_ACTIONS_ASSETS_DIR.rglob("*") if p.is_file())
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(actions.with_header("name: OLD\n", target.suffix, "0.0.1"), encoding="utf-8")

    # Without --force the stale file is left untouched...
    assert actions.cmd_init(_args(dest, wf)) == 0
    assert actions.managed_version(target.read_text()) == "0.0.1"

    # ...and --force re-stamps it at the current version.
    assert actions.cmd_init(_args(dest, wf, force=True)) == 0
    assert actions.managed_version(target.read_text()) == __version__
