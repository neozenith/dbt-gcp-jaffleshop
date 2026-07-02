"""Unit tests for the `gha` path-collapse engine (pure; no dbt, belongs in `make ci`)."""

# First Party
from adaf.gha.globber import (
    discover_to_globs,
    false_positives,
    glob_to_regex,
)

# A source-fed demand-like shape: two product dirs that differ in ONE component (cdm vs marts).
PATHS = {
    "models/cdm/demand/fact_a.sql",
    "models/cdm/demand/fact_b.sql",
    "models/marts/demand/dim_c.sql",
}


def test_strict_lists_every_file_verbatim() -> None:
    assert discover_to_globs(PATHS, "strict") == sorted(PATHS)


def test_leaf_collapses_filename_only_per_dir() -> None:
    assert discover_to_globs(PATHS, "leaf") == [
        "models/cdm/demand/*.{sql,yml}",
        "models/marts/demand/*.{sql,yml}",
    ]


def test_recursive_wildcards_the_one_varying_component() -> None:
    # cdm vs marts differ at index 1 → collapse to a single `**` glob.
    assert discover_to_globs(PATHS, "recursive") == ["models/**/demand/**"]


def test_recursive_subsumes_nested_dirs() -> None:
    paths = {"models/demand/a.sql", "models/demand/sub/b.sql"}
    # the parent `models/demand/**` covers the nested `models/demand/sub/**`.
    assert discover_to_globs(paths, "recursive") == ["models/demand/**"]


def test_default_mode_is_recursive() -> None:
    from adaf.gha.globber import DEFAULT_PATH_MODE

    assert DEFAULT_PATH_MODE == "recursive"
    assert discover_to_globs(PATHS, DEFAULT_PATH_MODE) == discover_to_globs(PATHS, "recursive")


def test_glob_to_regex_globstar_and_brace() -> None:
    rx = glob_to_regex("models/**/demand/**")
    assert rx.match("models/cdm/demand/x.sql")
    assert rx.match("models/a/b/demand/deep/y.sql")
    assert not rx.match("models/cdm/other/x.sql")
    leaf = glob_to_regex("models/cdm/demand/*.{sql,yml}")
    assert leaf.match("models/cdm/demand/fact_a.sql")
    assert leaf.match("models/cdm/demand/_schema.yml")
    assert not leaf.match("models/cdm/demand/sub/nested.sql")  # single * does not cross /


def test_false_positives_reports_overmatch_vs_strict() -> None:
    globs = discover_to_globs(PATHS, "recursive")  # ["models/**/demand/**"]
    universe = PATHS | {
        "models/cdm/other/x.sql",  # different product dir — NOT matched
        "models/x/demand/leaked.sql",  # another demand dir — matched, so a false positive
    }
    fps = false_positives(globs, universe, canonical=PATHS)
    assert fps == {"models/x/demand/leaked.sql"}


def test_strict_has_zero_false_positives() -> None:
    globs = discover_to_globs(PATHS, "strict")
    universe = PATHS | {"models/cdm/demand/unlisted.sql"}
    # strict lists exact files, so even a sibling in the same dir is not matched.
    assert false_positives(globs, universe, canonical=PATHS) == set()
