"""Unit tests for the pure, side-effect-free pieces of tfs: backend parsing, the
state-prefix convention, and the two-root discovery contract."""

import subprocess
from pathlib import Path

import pytest

from tfs.app import build_parser
from tfs.backends import parse_backend_config
from tfs.config import expected_prefix
from tfs.errors import InfraRootNotFoundError
from tfs.roots import find_infra_root, find_repo_root


@pytest.mark.parametrize(
    "content, expected",
    [
        ('bucket = "b"\nprefix = "p"\n', {"bucket": "b", "prefix": "p"}),
        ('# comment\nbucket = "b"\n\n', {"bucket": "b"}),
        ('bucket="quoted"\n', {"bucket": "quoted"}),
        ("", {}),
    ],
)
def test_parse_backend_config(tmp_path: Path, content: str, expected: dict):
    cfg = tmp_path / "dev.config"
    cfg.write_text(content)
    assert parse_backend_config(cfg) == expected


@pytest.mark.parametrize(
    "stack, expected",
    [
        ("dbt_platform", "terraform/state/dbt_platform"),  # migrated to the per-stack convention (was grandfathered)
        ("monitoring", "terraform/state/monitoring"),  # per-stack convention
    ],
)
def test_expected_prefix(stack: str, expected: str):
    assert expected_prefix(stack) == expected


def _make_infra(root: Path) -> Path:
    """Create a minimal infra-root shape (config.yml + stacks/) under root."""
    (root / "config.yml").write_text("environments: {}\n")
    (root / "stacks").mkdir()
    return root


def test_find_infra_root_walks_up(tmp_path: Path):
    infra = tmp_path / "infra"
    infra.mkdir(parents=True)
    _make_infra(infra)  # config.yml + stacks/ markers
    nested = infra / "stacks" / "x" / "backends"
    nested.mkdir(parents=True)
    assert find_infra_root(start=nested) == infra


def test_find_infra_root_override_validated(tmp_path: Path):
    not_infra = tmp_path / "nope"
    not_infra.mkdir()
    with pytest.raises(InfraRootNotFoundError):
        find_infra_root(override=str(not_infra))


def test_find_infra_root_not_found(tmp_path: Path):
    with pytest.raises(InfraRootNotFoundError):
        find_infra_root(start=tmp_path)


@pytest.mark.parametrize(
    "argv",
    [
        ["--infra-root", "/x", "validate"],  # global flag BEFORE the subcommand
        ["validate", "--infra-root", "/x"],  # global flag AFTER the subcommand
    ],
)
def test_infra_root_flag_survives_either_position(argv: list[str]):
    """Regression: parents=[common] + default=SUPPRESS means the subparser's unset
    occurrence must NOT clobber a value parsed at the top level (and vice versa)."""
    args = build_parser().parse_args(argv)
    assert args.infra_root == "/x"


def test_debug_defaults_when_absent():
    """SUPPRESS leaves --debug unset; getattr fallback must yield False."""
    args = build_parser().parse_args(["validate"])
    assert getattr(args, "debug", False) is False


def test_find_repo_root_uses_git_toplevel(tmp_path: Path):
    repo = tmp_path / "repo"
    infra = repo / "some" / "deep" / "infra"
    infra.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    # repo_root is git's toplevel — NOT infra.parent (which would be .../deep)
    assert find_repo_root(infra) == repo.resolve()
    assert find_repo_root(infra) != infra.parent
