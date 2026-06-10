# Standard Library
from pathlib import Path
from types import SimpleNamespace

# Local
from adaf.dbt import selection
from adaf.dbt.selection import Selection


def test_from_args_defaults_to_changed_only():
    ns = SimpleNamespace(all_models=False, base_ref="main", select=None, exclude=None)
    sel = selection.from_args(ns)
    assert sel.all_models is False
    assert sel.base_ref == "main"
    assert sel.select == [] and sel.exclude == []
    assert sel.has_selectors is False


def test_from_args_collects_repeated_selectors():
    ns = SimpleNamespace(all_models=True, base_ref="x", select=["staging", "marts"], exclude=["tag:wip"])
    sel = selection.from_args(ns)
    assert sel.select == ["staging", "marts"]
    assert sel.exclude == ["tag:wip"]
    assert sel.has_selectors is True


def test_describe_changed_default():
    assert selection.describe(Selection(base_ref="main")) == "changed models vs main"


def test_describe_all_with_select_and_exclude():
    text = selection.describe(Selection(all_models=True, select=["staging"], exclude=["stg_orders"]))
    assert "all models" in text
    assert "select=staging" in text
    assert "exclude=stg_orders" in text


def test_all_model_files_globs_recursively_sql_only(tmp_path: Path):
    (tmp_path / "models/staging").mkdir(parents=True)
    (tmp_path / "models/marts").mkdir(parents=True)
    (tmp_path / "models/staging/a.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "models/marts/b.sql").write_text("select 1", encoding="utf-8")
    (tmp_path / "models/staging/a.yml").write_text("x", encoding="utf-8")  # non-sql, must be ignored
    found = [str(p) for p in selection.all_model_files(tmp_path)]
    assert found == ["models/marts/b.sql", "models/staging/a.sql"]


def test_resolve_changed_intersects_with_dbt_ls(monkeypatch):
    monkeypatch.setattr(
        selection,
        "changed_model_files",
        lambda base_ref, cwd=None: [Path("models/staging/a.sql"), Path("models/marts/b.sql")],
    )
    monkeypatch.setattr(selection, "dbt_ls_paths", lambda sel, exc, cwd=None: {"models/staging/a.sql"})
    files = [str(p) for p in selection.resolve_model_files(Selection(select=["staging"]), cwd=Path("/x"))]
    assert files == ["models/staging/a.sql"]  # changed ∩ dbt selection


def test_resolve_all_without_selectors_uses_disk(tmp_path: Path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/a.sql").write_text("select 1", encoding="utf-8")
    files = [str(p) for p in selection.resolve_model_files(Selection(all_models=True), cwd=tmp_path)]
    assert files == ["models/a.sql"]
