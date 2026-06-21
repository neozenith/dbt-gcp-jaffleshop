"""Unit tests for the macro-dependency resolver and the TUI table renderer (pure; `make ci`)."""

# First Party
from adaf.dbt.manifest_view import ManifestView
from adaf.report import render_table

_MANIFEST = {
    "metadata": {"project_name": "adaf_demo"},
    "nodes": {
        "model.adaf_demo.fct": {
            "resource_type": "model",
            "original_file_path": "models/marts/fct.sql",
            "depends_on": {"macros": ["macro.adaf_demo.my_macro", "macro.dbt_utils.star"]},
        },
        "model.adaf_demo.other": {
            "resource_type": "model",
            "original_file_path": "models/other.sql",
            "depends_on": {"macros": []},
        },
    },
    "sources": {},
    "macros": {
        "macro.adaf_demo.my_macro": {"package_name": "adaf_demo", "original_file_path": "macros/my_macro.sql"},
        "macro.dbt_utils.star": {"package_name": "dbt_utils", "original_file_path": "macros/star.sql"},
    },
}


def test_dependent_macros_returns_repo_macros_only() -> None:
    view = ManifestView.from_dict(_MANIFEST)
    # fct depends on a repo macro and a package macro; only the repo one is a valid trigger path.
    assert view.dependent_macro_files({"model.adaf_demo.fct"}) == {"macros/my_macro.sql"}


def test_dependent_macros_excludes_package_macros() -> None:
    view = ManifestView.from_dict(_MANIFEST)
    files = view.dependent_macro_files({"model.adaf_demo.fct"})
    assert "macros/star.sql" not in files  # dbt_utils package macro lives outside the repo


def test_dependent_macros_empty_when_no_macro_deps() -> None:
    view = ManifestView.from_dict(_MANIFEST)
    assert view.dependent_macro_files({"model.adaf_demo.other"}) == set()


def test_render_table_draws_box_with_aligned_cells() -> None:
    out = render_table(["mode", "fp%"], [["recursive", "50.0%"], ["strict", "0.0%"]], aligns=["l", "r"])
    lines = out.splitlines()
    assert lines[0].startswith("┌") and lines[-1].startswith("└")
    assert "│ mode      │   fp% │" == lines[1]  # left-pad "mode", right-pad "fp%" to column widths
    assert "│ recursive │ 50.0% │" in out
