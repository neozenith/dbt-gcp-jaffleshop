"""Unit tests for the sdag ``--archive`` zip bundler (real files + real zipfile, no mocks).

Two halves:

* :func:`viewer.write_archive` is driven against a tmp output dir populated with fake viewer
  assets — asserting the zip exists, its ``namelist()`` is exactly the present viewer files at the
  archive root, and the bytes round-trip (self-contained), plus the fail-loud paths.
* The CLI wiring (``--archive`` argparse + :func:`dataproducts._archive_path`) is exercised through
  the real parser so bare ``--archive``, ``--archive PATH`` and no-flag resolve to the right zip path.
"""

# Standard Library
import zipfile
from pathlib import Path

# Third Party
import pytest

# First Party
from adaf import viewer
from adaf.app import build_parser
from adaf.commands import dataproducts


def _populate(output_dir: Path, files: tuple[str, ...] = viewer.VIEWER_FILES) -> dict[str, str]:
    """Write a fake viewer build into ``output_dir``; return {name: contents} for round-trip checks."""
    output_dir.mkdir(parents=True, exist_ok=True)
    contents = {name: f"// fake {name}\n{'x' * 50}" for name in files}
    for name, body in contents.items():
        (output_dir / name).write_text(body, encoding="utf-8")
    return contents


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


# ─── write_archive ───────────────────────────────────────────────────────────


def test_write_archive_bundles_all_viewer_files(tmp_path: Path) -> None:
    out = tmp_path / "sdag"
    contents = _populate(out)
    zip_path = tmp_path / "sdag.zip"

    entries = viewer.write_archive(out, zip_path)

    assert zip_path.is_file()
    assert entries == sorted(viewer.VIEWER_FILES)
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == sorted(viewer.VIEWER_FILES)
        for name, body in contents.items():
            assert zf.read(name).decode("utf-8") == body


def test_write_archive_inline_build_is_single_file(tmp_path: Path) -> None:
    """An --inline build holds only sdag.html; the archive is that one self-contained file."""
    out = tmp_path / "sdag"
    _populate(out, files=(viewer.SDAG_HTML,))
    zip_path = tmp_path / "sdag.zip"

    entries = viewer.write_archive(out, zip_path)

    assert entries == [viewer.SDAG_HTML]
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == [viewer.SDAG_HTML]


def test_write_archive_ignores_non_viewer_files(tmp_path: Path) -> None:
    out = tmp_path / "sdag"
    _populate(out)
    (out / "stray.txt").write_text("not a viewer asset", encoding="utf-8")
    (out / "sdag.zip").write_text("a previous archive", encoding="utf-8")
    zip_path = tmp_path / "out.zip"

    viewer.write_archive(out, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        assert "stray.txt" not in zf.namelist()
        assert "sdag.zip" not in zf.namelist()


def test_write_archive_fails_loud_when_output_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        viewer.write_archive(tmp_path / "nope", tmp_path / "sdag.zip")


def test_write_archive_fails_loud_when_no_assets(tmp_path: Path) -> None:
    empty = tmp_path / "sdag"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="nothing to archive"):
        viewer.write_archive(empty, tmp_path / "sdag.zip")


# ─── CLI wiring / _archive_path ──────────────────────────────────────────────


def test_archive_flag_defaults_to_none() -> None:
    args = _parse(["products", "generate"])
    assert args.archive is None
    assert dataproducts._archive_path(args) is None


def test_bare_archive_resolves_into_output_dir() -> None:
    args = _parse(["products", "generate", "--archive", "-o", "tmp/sdag"])
    assert args.archive == dataproducts.ARCHIVE_DEFAULT
    assert dataproducts._archive_path(args) == Path("tmp/sdag") / "sdag.zip"


def test_archive_with_explicit_path() -> None:
    args = _parse(["products", "generate", "--archive", "tmp/foo.zip"])
    assert dataproducts._archive_path(args) == Path("tmp/foo.zip")


def test_archive_flag_available_on_serve() -> None:
    args = _parse(["products", "serve", "--archive", "tmp/bar.zip"])
    assert dataproducts._archive_path(args) == Path("tmp/bar.zip")


def test_cmd_generate_writes_archive_end_to_end(tmp_path: Path) -> None:
    """Drive the bundler the way cmd_generate does against a real populated output dir."""
    out = tmp_path / "sdag"
    _populate(out)
    args = _parse(["products", "generate", "--archive", "-o", str(out)])
    zip_path = dataproducts._archive_path(args)
    assert zip_path == out / "sdag.zip"

    entries = viewer.write_archive(out, zip_path)

    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == sorted(entries) == sorted(viewer.VIEWER_FILES)
