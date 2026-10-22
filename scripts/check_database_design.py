"""Check retained database design against metadata; optional MySQL audit is read-only."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

from sqlalchemy import Boolean, create_engine
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateTable

from app.persistence import auth, journal  # noqa: F401 -- register all eight tables
from app.persistence.schema import SCHEMA_VERSION, metadata
from app.persistence.validation import foreign_key_signature as _foreign_key_signature, schema_differences


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_ROOT = PROJECT_ROOT / "docs/design/database"
INITIAL_SQL = DESIGN_ROOT / "sql/001-initial-schema.sql"
SQL_HEADER = """-- Aesir AI Service: MySQL 8.4+ schema v1, empty application database only.
-- Generated from SQLAlchemy metadata; check with python -m scripts.check_database_design.
-- No CREATE DATABASE, GRANT, USE, DROP, IF NOT EXISTS, or credential material.
-- DDL auto-commits in MySQL. Stop on the first error; never use mysql --force.
-- Mark v1 only after all eight CREATE TABLE statements have succeeded.

"""


def render_initial_sql() -> str:
    statements = [
        str(CreateTable(table).compile(dialect=mysql.dialect())).strip() + ";"
        for table in metadata.sorted_tables
    ]
    statements.append(
        f"INSERT INTO schema_versions (id, version) VALUES (1, {SCHEMA_VERSION});"
    )
    rendered = SQL_HEADER + "\n\n".join(statements) + "\n"
    return "\n".join(line.rstrip() for line in rendered.splitlines()) + "\n"


def _plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def check_artifacts(design_root: Path | None = None) -> list[str]:
    design_root = design_root or DESIGN_ROOT
    initial_sql = design_root / "sql/001-initial-schema.sql"
    errors = []
    if not initial_sql.is_file():
        errors.append("initial_sql: missing")
    elif initial_sql.read_text(encoding="utf-8") != render_initial_sql():
        errors.append("initial_sql: differs from current MySQL metadata rendering")
    dictionary = design_root / "03-data-dictionary.md"
    content = dictionary.read_text(encoding="utf-8") if dictionary.is_file() else ""
    for table in metadata.sorted_tables:
        section = re.search(
            rf"^## \d+\. {re.escape(table.name)}\s*$(.*?)(?=^## |\Z)",
            content, re.MULTILINE | re.DOTALL,
        )
        if section is None:
            errors.append(f"dictionary: missing table {table.name}")
            continue
        rows = {}
        for line in section.group(1).splitlines():
            if not re.match(r"^\| `[^`]+` \|", line):
                continue
            fields = [field.strip() for field in line.strip().strip("|").split("|")]
            name = fields[0].strip("`")
            if name in rows:
                errors.append(f"dictionary: duplicate column {table.name}.{name}")
            rows[name] = fields
        if set(rows) != set(table.c.keys()):
            errors.append(f"dictionary: column set differs for {table.name}")
        for column in table.c:
            row = rows.get(column.name)
            label = f"dictionary: {table.name}.{column.name}"
            if row is None:
                continue
            if len(row) != 7:
                errors.append(f"{label} requires seven dictionary fields")
                continue
            expected_type = str(column.type.compile(dialect=mysql.dialect()))
            allowed_types = {expected_type}
            if isinstance(column.type, Boolean):
                allowed_types.update({"TINYINT(1)", "TINYINT(1) / BOOL"})
            if row[1] not in allowed_types:
                errors.append(f"{label} type differs")
            if row[2] != ("是" if column.nullable else "否"):
                errors.append(f"{label} nullable differs")
            flags = set(re.findall(r"\b(PK|FK|AUTO_INCREMENT)(?:\d+)?\b", row[3]))
            expected_flags = set()
            if column.primary_key:
                expected_flags.add("PK")
            if column.foreign_keys:
                expected_flags.add("FK")
            if table._autoincrement_column is column:
                expected_flags.add("AUTO_INCREMENT")
            if flags != expected_flags:
                errors.append(f"{label} key/auto increment flags differ")
            expected_default = "NULL（隐式）" if column.nullable else "无"
            if table._autoincrement_column is column:
                expected_default = "无固定DEFAULT"
            if column.server_default is None and row[4] != expected_default:
                errors.append(f"{label} server-default wording differs")
    diagrams = sorted((design_root / "src").glob("*pdm*.drawio"))
    if not diagrams:
        errors.append("pdm: missing editable source")
    cells = {}
    for diagram in diagrams:
        try:
            for cell in ET.parse(diagram).iter("mxCell"):
                if cell.get("id") in cells:
                    errors.append(f"pdm: duplicate cell id {cell.get('id')}")
                cells[cell.get("id")] = cell
        except ET.ParseError:
            errors.append(f"pdm: invalid XML {diagram.name}")
    expected_tables = {f"table_{table.name}" for table in metadata.sorted_tables}
    expected_columns = {f"col_{table.name}_{column.name}" for table in metadata.sorted_tables for column in table.c}
    if {key for key in cells if key and key.startswith("table_")} != expected_tables:
        errors.append("pdm: table set differs")
    if {key for key in cells if key and key.startswith("col_")} != expected_columns:
        errors.append("pdm: column set differs")
    for table in metadata.sorted_tables:
        table_id = f"table_{table.name}"
        table_cell = cells.get(table_id)
        if table_cell is None:
            errors.append(f"pdm: missing table {table.name}")
        elif (table_cell.get("vertex") != "1" or table_cell.get("parent") != "1"
              or not re.match(rf"{re.escape(table.name)}(?:\s|$)", _plain(table_cell.get("value", "")))):
            errors.append(f"pdm: table identity differs for {table.name}")
        for column in table.c:
            cell = cells.get(f"col_{table.name}_{column.name}")
            if cell is None:
                errors.append(f"pdm: missing column {table.name}.{column.name}")
                continue
            label = f"pdm: {table.name}.{column.name}"
            if cell.get("parent") != table_id or cell.get("vertex") != "1":
                errors.append(f"{label} parent/vertex differs")
            value = _plain(cell.get("value", ""))
            sql_type = str(column.type.compile(dialect=mysql.dialect()))
            match = re.fullmatch(rf"{re.escape(column.name)}\s+{re.escape(sql_type)}\s+((?:PK|FK|NN|NULL|AI)(?:\s+(?:PK|FK|NN|NULL|AI))*)", value)
            if match is None:
                errors.append(f"{label} name/type/flag format differs")
                continue
            tokens = match.group(1).split()
            expected_flags = {"NULL" if column.nullable else "NN"}
            if column.primary_key:
                expected_flags.add("PK")
            if column.foreign_keys:
                expected_flags.add("FK")
            if table._autoincrement_column is column:
                expected_flags.add("AI")
            if set(tokens) != expected_flags or len(tokens) != len(expected_flags):
                errors.append(f"{label} flags differ")
    expected_edges = {}
    for table in metadata.sorted_tables:
        for fk in table.foreign_key_constraints:
            expected_edges[f"fk_{table.name}"] = (f"table_{fk.referred_table.name}", f"table_{table.name}")
    actual_edges = {key: cell for key, cell in cells.items() if cell.get("edge") == "1"}
    if set(actual_edges) != set(expected_edges):
        errors.append("pdm: physical FK edge set differs")
    for key, (source, target) in expected_edges.items():
        edge = actual_edges.get(key)
        if edge is None:
            continue
        style = dict(part.split("=", 1) for part in edge.get("style", "").split(";") if "=" in part)
        if edge.get("source") != source or edge.get("target") != target or edge.get("parent") != "1":
            errors.append(f"pdm: {key} endpoints differ")
        if style.get("dashed", "0") != "0":
            errors.append(f"pdm: {key} must be solid")
    return errors


def audit_mysql(url_file: Path) -> list[str]:
    """Inspect structure only. No DDL, DML, business row values, or DSNs in output."""
    if os.name == "posix" and stat.S_IMODE(url_file.stat().st_mode) & 0o077:
        raise ValueError("Connection file must not be accessible by group or others")
    url = make_url(url_file.read_text(encoding="utf-8").strip())
    if url.drivername != "mysql+pymysql":
        raise ValueError("Only MySQL/PyMySQL inspection is supported")
    engine = create_engine(url, pool_pre_ping=True)
    errors = []
    try:
        with engine.connect() as connection:
            if engine.dialect.is_mariadb or engine.dialect.server_version_info < (8, 4):
                errors.append("database: requires MySQL 8.4+")
            errors.extend(schema_differences(connection))
    finally:
        engine.dispose()
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-sql", action="store_true", help="Print regenerated initial DDL, without connecting")
    parser.add_argument("--database-url-file", type=Path, help="Optional private 0600 MySQL connection file; read-only audit")
    args = parser.parse_args()
    if args.print_sql:
        print(render_initial_sql(), end="")
        return 0
    errors = check_artifacts()
    if args.database_url_file:
        try:
            errors.extend(audit_mysql(args.database_url_file))
        except (OSError, ValueError, SQLAlchemyError) as error:
            # Exception text can include DSNs or SQL values; expose only its class.
            errors.append(f"database: inspection failed ({type(error).__name__})")
    print(json.dumps({"schema_version": SCHEMA_VERSION, "tables": len(metadata.tables),
                      "columns": sum(len(table.c) for table in metadata.tables.values()),
                      "mysql_inspected": args.database_url_file is not None,
                      "ok": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
