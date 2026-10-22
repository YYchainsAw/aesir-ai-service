"""Exercise design gates with plausible documentation/schema drift, without DB writes."""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from scripts.check_database_design import (
    DESIGN_ROOT, _foreign_key_signature, check_artifacts,
)


@pytest.fixture
def design(tmp_path):
    target = tmp_path / "database"
    for relative in (
        "sql/001-initial-schema.sql", "03-data-dictionary.md",
        "src/02-npc-persistence-pdm.drawio",
    ):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DESIGN_ROOT / relative, destination)
    return target


def test_current_design_matches_registered_metadata():
    assert check_artifacts() == []


def test_retained_sql_must_match_metadata(design):
    path = design / "sql/001-initial-schema.sql"
    path.write_text(path.read_text(encoding="utf-8").replace("expires_at DOUBLE NOT NULL", "expires_at FLOAT NOT NULL"), encoding="utf-8")
    assert any(error.startswith("initial_sql:") for error in check_artifacts(design))


@pytest.mark.parametrize("cell_id,attribute,value", [
    ("col_access_quotas_game_id", "value", "game_id VARCHAR(100) PK FK NN"),
    ("col_operation_journal_result", "value", "result JSON NN"),
    ("col_documents_version", "value", "version BIGINT PK NN"),
    ("col_documents_version", "value", "version BIGINT NN AI"),
    ("col_documents_version", "parent", "table_operation_journal"),
    ("fk_access_save_grants", "target", "table_access_quotas"),
    ("fk_access_credentials", "style", "dashed=1"),
])
def test_pdm_rejects_false_constraints_and_associations(design, cell_id, attribute, value):
    path = design / "src/02-npc-persistence-pdm.drawio"
    tree = ET.parse(path)
    tree.find(f".//mxCell[@id='{cell_id}']").set(attribute, value)
    tree.write(path, encoding="utf-8")
    assert any(error.startswith("pdm:") for error in check_artifacts(design))


def test_pdm_rejects_extra_tables_and_columns(design):
    path = design / "src/02-npc-persistence-pdm.drawio"
    tree = ET.parse(path)
    root = tree.find(".//root")
    ET.SubElement(root, "mxCell", id="table_unimplemented", value="unimplemented", parent="1", vertex="1")
    ET.SubElement(root, "mxCell", id="col_documents_phantom", value="phantom INTEGER NN", parent="table_documents", vertex="1")
    tree.write(path, encoding="utf-8")
    errors = check_artifacts(design)
    assert "pdm: table set differs" in errors
    assert "pdm: column set differs" in errors


@pytest.mark.parametrize("change", ["missing", "type", "nullable", "fake_fk"])
def test_dictionary_rejects_column_or_constraint_drift(design, change):
    path = design / "03-data-dictionary.md"
    content = path.read_text(encoding="utf-8")
    row = next(line for line in content.splitlines() if line.startswith("| `expires_at` |"))
    changed = {"missing": "", "type": row.replace("DOUBLE", "FLOAT"),
               "nullable": row.replace("| 否 |", "| 是 |"),
               "fake_fk": row.replace("| — |", "| FK |")}[change]
    path.write_text(content.replace(row, changed), encoding="utf-8")
    assert any(error.startswith("dictionary:") for error in check_artifacts(design))


def test_foreign_key_to_another_schema_is_not_local():
    base = {"constrained_columns": ["game_id", "player_id"],
            "referred_schema": None, "referred_table": "access_players",
            "referred_columns": ["game_id", "player_id"], "options": {}}
    local = _foreign_key_signature(base, "current_database")
    assert _foreign_key_signature({**base, "referred_schema": "current_database"}, "current_database") == local
    assert _foreign_key_signature({**base, "referred_schema": "another_database"}, "current_database") != local
