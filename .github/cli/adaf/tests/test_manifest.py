# Local
from adaf.manifest import Manifest

from conftest import MANIFEST_DATA


def test_only_model_nodes_are_indexed(manifest: Manifest):
    # The seed and test nodes must not appear as models.
    assert set(manifest.by_path()) == {
        "models/marts/documented.sql",
        "models/staging/partial_cols.sql",
        "models/marts/no_desc.sql",
    }


def test_test_nodes_are_tallied_onto_their_models(manifest: Manifest):
    by_path = manifest.by_path()
    assert by_path["models/marts/documented.sql"].test_count == 2
    assert by_path["models/staging/partial_cols.sql"].test_count == 0
    assert by_path["models/marts/no_desc.sql"].test_count == 0


def test_column_descriptions_are_extracted(manifest: Manifest):
    columns = manifest.by_path()["models/staging/partial_cols.sql"].columns
    assert columns == {"id": "the id", "blank": ""}


def test_from_dict_tolerates_missing_optional_keys():
    # A model node with no description/columns must not raise and must default cleanly.
    manifest = Manifest.from_dict(
        {"nodes": {"model.p.m": {"resource_type": "model", "name": "m", "original_file_path": "models/m.sql"}}}
    )
    model = manifest.by_path()["models/m.sql"]
    assert model.description == "" and model.columns == {} and model.test_count == 0


def test_loads_from_real_manifest_data_constant():
    # Sanity check the constant is wired to the loader the same way load() is.
    assert Manifest.from_dict(MANIFEST_DATA).by_path()["models/marts/documented.sql"].name == "documented"
