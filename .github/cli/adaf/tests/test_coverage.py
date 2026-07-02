"""Unit tests for the manifest-backed coverage gates — real manifest JSON + schema YAML on disk.

No mocks: each test writes a synthetic ``manifest.json`` (and, where a line anchor is asserted, the
matching schema YAML) into ``tmp_path``, loads it through the real :class:`Manifest`, and checks the
stderr headline / stdout findings split via ``capsys``.
"""

# Standard Library
import json
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf.commands import coverage
from adaf.commands.coverage import _find_model_line, _strip_scheme
from adaf.dbt.manifest import Manifest

# A schema YAML where model `a` is documented and `b` is not; `a` lands on line 3, `b` on line 5.
_SCHEMA_YML = """version: 2
models:
  - name: a
    description: the a model
  - name: b
"""


def _manifest_dict() -> dict:
    """Two models (a: documented + 2 tests; b: undocumented + untested), both patched by one schema YAML."""
    return {
        "nodes": {
            "model.p.a": {
                "resource_type": "model",
                "name": "a",
                "original_file_path": "models/a.sql",
                "patch_path": "p://models/_schema.yml",
                "description": "the a model",
                "columns": {},
            },
            "model.p.b": {
                "resource_type": "model",
                "name": "b",
                "original_file_path": "models/b.sql",
                "patch_path": "p://models/_schema.yml",
                "description": "",
                "columns": {},
            },
            "test.p.t1": {"resource_type": "test", "depends_on": {"nodes": ["model.p.a"]}},
            "test.p.t2": {"resource_type": "test", "depends_on": {"nodes": ["model.p.a"]}},
        }
    }


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Manifest, Path]:
    """Lay down a manifest.json + schema YAML under a tmp project root and chdir into it.

    Chdir matters: the schema location is repo-relative (``models/_schema.yml``), so ``_find_model_line``
    resolves it against the project root — here, ``tmp_path``.
    """
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "_schema.yml").write_text(_SCHEMA_YML, encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_dict()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return Manifest.load(manifest_path), manifest_path


# --- pure helpers ---------------------------------------------------------------------------------


def test_strip_scheme_removes_project_scheme() -> None:
    assert _strip_scheme("bq://models/staging/_x.yml") == "models/staging/_x.yml"


def test_strip_scheme_passthrough_when_no_scheme() -> None:
    assert _strip_scheme("models/_x.yml") == "models/_x.yml"


def test_find_model_line_locates_entries(tmp_path: Path) -> None:
    yml = tmp_path / "_schema.yml"
    yml.write_text(_SCHEMA_YML, encoding="utf-8")
    assert _find_model_line(yml, "a") == 3
    assert _find_model_line(yml, "b") == 5


def test_find_model_line_missing_name_or_file(tmp_path: Path) -> None:
    yml = tmp_path / "_schema.yml"
    yml.write_text(_SCHEMA_YML, encoding="utf-8")
    assert _find_model_line(yml, "nope") is None
    assert _find_model_line(tmp_path / "absent.yml", "a") is None


# --- docscov --------------------------------------------------------------------------------------


def test_docscov_all_documented_returns_zero(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs([Path("models/a.sql")], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "OK" in out.err  # headline on stderr
    assert out.out == ""  # no findings on stdout


def test_docscov_no_files_returns_zero(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs([], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "skipped" in out.err
    assert out.out == ""


def test_docscov_gap_points_at_schema_line(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs(
        [Path("models/a.sql"), Path("models/b.sql")], manifest, scope="x", manifest_path=manifest_path
    )
    out = capsys.readouterr()
    assert rc == 1
    # Summary headline on stderr; findings on stdout.
    assert "1 of 2" in out.err
    assert "models/_schema.yml:5" in out.out  # b's entry line
    assert "DOCSCOV" in out.out
    assert "no description" in out.out
    assert "models/a.sql" not in out.out  # a is documented — not a finding


def test_docscov_gap_emits_remediation_guidance_once(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs(
        [Path("models/a.sql"), Path("models/b.sql")], manifest, scope="x", manifest_path=manifest_path
    )
    out = capsys.readouterr()
    assert rc == 1
    # Guidance is a trailing help line on stderr (the headline channel), not a per-finding stdout line.
    assert "add a `description:`" in out.err
    assert "https://docs.getdbt.com/reference/resource-properties/description" in out.err
    assert out.err.count("https://docs.getdbt.com/reference/resource-properties/description") == 1
    assert "https://docs.getdbt.com" not in out.out  # guidance stays off the findings list


def test_docscov_clean_run_has_no_guidance(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs([Path("models/a.sql")], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "https://docs.getdbt.com" not in out.err
    assert "add a `description:`" not in out.err


def test_docscov_without_manifest_path_falls_back_to_sql(project, capsys) -> None:
    manifest, _ = project
    rc = coverage.check_docs([Path("models/b.sql")], manifest, scope="x")  # no manifest_path
    out = capsys.readouterr()
    assert rc == 1
    assert "models/b.sql" in out.out  # fell back to the .sql path
    assert ".yml" not in out.out


def test_docscov_not_in_manifest_falls_back_to_sql(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_docs([Path("models/ghost.sql")], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 1
    assert "models/ghost.sql" in out.out
    assert "not in manifest" in out.out


# --- testcov --------------------------------------------------------------------------------------


def test_testcov_all_tested_returns_zero(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_tests([Path("models/a.sql")], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "OK" in out.err
    assert out.out == ""


def test_testcov_gap_points_at_schema_line(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_tests(
        [Path("models/a.sql"), Path("models/b.sql")], manifest, scope="x", manifest_path=manifest_path
    )
    out = capsys.readouterr()
    assert rc == 1
    assert "1 of 2" in out.err
    assert "models/_schema.yml:5" in out.out  # b is untested
    assert "TESTCOV" in out.out
    assert "no tests" in out.out
    assert "models/a.sql" not in out.out  # a has two tests


def test_testcov_gap_emits_remediation_guidance_once(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_tests(
        [Path("models/a.sql"), Path("models/b.sql")], manifest, scope="x", manifest_path=manifest_path
    )
    out = capsys.readouterr()
    assert rc == 1
    assert "add `data_tests:`" in out.err
    assert "https://docs.getdbt.com/reference/resource-properties/data-tests" in out.err
    assert out.err.count("https://docs.getdbt.com/reference/resource-properties/data-tests") == 1
    assert "https://docs.getdbt.com" not in out.out


def test_testcov_clean_run_has_no_guidance(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_tests([Path("models/a.sql")], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "https://docs.getdbt.com" not in out.err
    assert "add `data_tests:`" not in out.err


def test_testcov_no_files_returns_zero(project, capsys) -> None:
    manifest, manifest_path = project
    rc = coverage.check_tests([], manifest, scope="x", manifest_path=manifest_path)
    out = capsys.readouterr()
    assert rc == 0
    assert "skipped" in out.err
    assert out.out == ""
