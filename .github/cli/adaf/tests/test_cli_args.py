"""Unit tests for CLI arg wiring + Selection assembly (real argparse, no mocks)."""

# Third Party
import pytest

# First Party
from adaf.app import build_parser
from adaf.commands.defer import cmd_defer_state
from adaf.dbt.selection import UNBOUNDED, from_args


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


def test_target_flows_into_selection() -> None:
    args = _parse(["list", "--all", "--selector", "demand", "--target", "test"])
    sel = from_args(args)
    assert sel.target == "test"
    assert sel.selector == "demand"
    assert sel.all_models is True


def test_target_defaults_to_none() -> None:
    sel = from_args(_parse(["list", "--all", "--selector", "demand"]))
    assert sel.target is None


def test_sqlfluff_format_flag_parses() -> None:
    args = _parse(["sqlfluff", "--all", "--selector", "demand", "--format", "github-annotation-native"])
    assert args.fmt == "github-annotation-native"


def test_sqlfluff_format_defaults_none() -> None:
    assert _parse(["sqlfluff", "--all", "--selector", "demand"]).fmt is None


@pytest.mark.parametrize("cmd", [["docscov"], ["testcov"], ["sqlfluff"], ["deprecations"], ["sdag", "check"]])
def test_quiet_is_suppressed_so_handlers_must_use_getattr(cmd: list[str]) -> None:
    # `-q/--quiet` uses argparse.SUPPRESS: WITHOUT it the attribute is ABSENT (not False), so a handler
    # doing `args.quiet` raises AttributeError. This pins that contract (a real regression the
    # multiversion suite caught) — every check handler must read it via getattr(args, "quiet", False).
    args = _parse([*cmd, "--all", "--selector", "demand"])
    assert not hasattr(args, "quiet")
    assert getattr(args, "quiet", False) is False
    args_q = _parse(["-q", *cmd, "--all", "--selector", "demand"])
    assert args_q.quiet is True


@pytest.mark.parametrize("cmd", [["docscov"], ["testcov"], ["sqlfluff"], ["deprecations"], ["sdag", "check"]])
def test_json_out_is_present_and_defaults_none(cmd: list[str]) -> None:
    # `--json-out` (unlike --quiet) is a normal arg ⇒ always present, default None — so handlers read it directly.
    assert _parse([*cmd, "--all", "--selector", "demand"]).json_out is None
    args = _parse([*cmd, "--all", "--selector", "demand", "--json-out", "f.json"])
    assert args.json_out.name == "f.json"


def test_defer_state_subcommand_wires_handler() -> None:
    args = _parse(["defer-state", "--defer-ref", "main", "--target", "test"])
    assert args.func is cmd_defer_state
    assert args.defer_ref == "main"
    assert args.target == "test"
    assert args.force is False


def test_ls_defer_flag_flows_into_selection() -> None:
    # `adaf ls --defer` is what now drives the built/deferred subgroup split (defer-diff is gone).
    sel = from_args(_parse(["list", "--all", "--selector", "demand", "--defer"]))
    assert sel.defer is True
    assert sel.all_models is True


def test_defer_diff_subcommand_is_removed() -> None:
    # The standalone defer-diff subcommand was folded into `adaf ls --defer`; invoking it is an error.
    with pytest.raises(SystemExit):
        _parse(["defer-diff", "--selector", "demand"])


def test_defer_target_distinct_from_target() -> None:
    sel = from_args(_parse(["list", "--all", "--selector", "demand", "--target", "dev", "--defer-target", "nonprod"]))
    assert sel.target == "dev"
    assert sel.defer_target == "nonprod"
    assert sel.effective_defer_target == "nonprod"  # explicit defer-target wins


def test_effective_defer_target_falls_back_to_target() -> None:
    sel = from_args(_parse(["list", "--all", "--selector", "demand", "--target", "dev"]))
    assert sel.defer_target is None
    assert sel.effective_defer_target == "dev"  # absent --defer-target → same as --target


def test_defer_state_accepts_defer_target() -> None:
    args = _parse(["defer-state", "--defer-ref", "main", "--target", "dev", "--defer-target", "nonprod"])
    assert args.target == "dev"
    assert args.defer_target == "nonprod"


def test_sdag_check_uses_the_shared_scope_core() -> None:
    # Same scope flags as the file gates: --selector + --changed-only/--all + --defer.
    args = _parse(["sdag", "check", "--all", "--selector", "demand", "--defer", "--defer-ref", "main"])
    assert args.selector == "demand"
    assert args.all_models is True
    assert args.defer is True
    assert args.defer_ref == "main"


def test_sdag_check_requires_selector() -> None:
    # --selector is REQUIRED now (identical to the other checks); omitting it is a usage error.
    with pytest.raises(SystemExit):
        _parse(["sdag", "check"])


def test_hop_flags_default_none() -> None:
    sel = from_args(_parse(["list", "--all", "--selector", "demand"]))
    assert sel.upstream is None
    assert sel.downstream is None
    assert sel.expands is False


def test_bare_hop_flags_are_unbounded() -> None:
    args = _parse(["list", "--all", "--selector", "demand", "--upstream", "--downstream"])
    assert args.upstream == UNBOUNDED
    assert args.downstream == UNBOUNDED
    sel = from_args(args)
    assert sel.upstream == UNBOUNDED
    assert sel.downstream == UNBOUNDED
    assert sel.expands is True


def test_hop_flags_take_int_counts() -> None:
    args = _parse(["sdag", "check", "--all", "--selector", "demand", "--upstream", "2", "--downstream", "3"])
    assert args.upstream == 2
    assert args.downstream == 3
    sel = from_args(args)
    assert sel.upstream == 2
    assert sel.downstream == 3


def test_color_defaults_to_auto() -> None:
    assert _parse(["list", "--all", "--selector", "demand"]).color == "auto"


def test_color_flag_parses_choice() -> None:
    assert _parse(["sqlfluff", "--all", "--selector", "demand", "--color", "always"]).color == "always"


def test_color_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        _parse(["list", "--all", "--selector", "demand", "--color", "rainbow"])
