"""Catalogue integrity tests — the SSoT guard, as pytest.

No mocks: these assert real invariants over the real ``catalog.json`` so a bad
edit fails CI loudly. The strongest one (``test_catalog_conforms_to_schema``) is
the programmatic form of "the catalogue cannot drift from its own contract".
"""

from adaf.rules import all_rules, load_catalog, rule_codes, validate_catalog


def test_catalog_conforms_to_schema() -> None:
    assert validate_catalog() == []


def test_rule_codes_are_unique() -> None:
    codes = rule_codes()
    assert len(codes) == len(set(codes))


def test_detection_values_are_declared_modes() -> None:
    modes = set(load_catalog()["detection_modes"])
    assert {r["detection"] for r in all_rules()} <= modes


def test_dama_values_are_the_six_dimensions() -> None:
    six = set(load_catalog()["dama_dimensions"])
    for rule in all_rules():
        assert set(rule["dama"]) <= six, f"{rule['code']} has a non-DAMA dimension"


def test_wang_strong_values_are_declared_dimensions() -> None:
    ws = load_catalog()["wang_strong"]
    declared = set(ws["intrinsic"] + ws["contextual"] + ws["representational"] + ws["accessibility"])
    for rule in all_rules():
        assert set(rule["wang_strong"]) <= declared, f"{rule['code']} has an undeclared Wang–Strong dimension"


def test_slug_matches_vignette_filename() -> None:
    # Vignette filenames are prefixed with the rule code: <code>-<slug>.md
    # (so the file sorts/identifies by rule code). The doc path must end with exactly that.
    for rule in all_rules():
        assert rule["doc"].endswith(f"/{rule['code']}-{rule['slug']}.md"), rule["code"]


def test_time_rules_have_subrole_others_do_not() -> None:
    for rule in all_rules():
        if rule["role"] == "time":
            assert "sub_role" in rule, f"{rule['code']} (time) is missing sub_role"
        else:
            assert "sub_role" not in rule, f"{rule['code']} ({rule['role']}) should not carry sub_role"
