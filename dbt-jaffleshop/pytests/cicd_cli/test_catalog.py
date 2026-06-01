# Local
from cicd_cli.catalog import Catalog


def test_columns_for_returns_actual_columns_in_catalog_order():
    cat = Catalog.from_dict({"nodes": {"model.p.m": {"columns": {"a": {}, "b": {}, "c": {}}}}})
    assert cat.columns_for("model.p.m") == ["a", "b", "c"]


def test_columns_for_missing_node_returns_none():
    cat = Catalog.from_dict({"nodes": {}})
    assert cat.columns_for("model.p.absent") is None


def test_node_without_columns_returns_empty_list():
    cat = Catalog.from_dict({"nodes": {"model.p.m": {}}})
    assert cat.columns_for("model.p.m") == []
