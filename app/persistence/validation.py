"""Read-only application schema checks shared by runtime and operator tooling.

SQLAlchemy metadata is the physical specification. Diagnostic differences contain
only source-defined object names; callers must not expose them in HTTP errors.
"""
from __future__ import annotations

from importlib import import_module

from sqlalchemy import UniqueConstraint, inspect, select

from app.persistence.schema import SCHEMA_VERSION, metadata, schema_versions


def application_metadata():
    """Register the full schema even before any optional service has imported it."""
    for module in ("app.persistence.auth", "app.persistence.journal"):
        import_module(module)
    return metadata


def _type_name(value, dialect):
    rendered = str(value.compile(dialect=dialect)).upper()
    return {"TINYINT(1)": "BOOL", "BOOLEAN": "BOOL", "INT": "INTEGER"}.get(rendered, rendered)


def _action(value):
    value = (value or "RESTRICT").upper()
    return "RESTRICT" if value == "NO ACTION" else value


def foreign_key_signature(fk, current_schema):
    schema = fk.get("referred_schema")
    if schema in {None, current_schema}:
        schema = None
    options = fk.get("options") or {}
    return (tuple(fk["constrained_columns"]), schema, fk["referred_table"],
            tuple(fk["referred_columns"]),
            _action(options.get("ondelete")), _action(options.get("onupdate")))


def schema_differences(connection):
    """Inspect eight v1 tables and the version marker without DDL/business reads.

    SQLite is supported for isolated tests. Engine/charset and auto-increment
    reflection are MySQL-specific. Collation is enforced only if metadata fixes it.
    """
    expected = application_metadata()
    inspector = inspect(connection)
    dialect = connection.dialect
    mysql = dialect.name == "mysql"
    current_schema = inspector.default_schema_name
    errors = []
    actual_tables = set(inspector.get_table_names())
    if set(expected.tables) != actual_tables:
        errors.append("tables: names differ from application metadata")
    for table in expected.sorted_tables:
        if table.name not in actual_tables:
            continue
        prefix = table.name
        actual_columns = inspector.get_columns(table.name)
        if [column.name for column in table.c] != [column["name"] for column in actual_columns]:
            errors.append(f"{prefix}: column names/order differ")
        by_name = {column["name"]: column for column in actual_columns}
        for column in table.c:
            actual = by_name.get(column.name)
            if actual is None:
                continue
            label = f"{prefix}.{column.name}"
            if _type_name(actual["type"], dialect) != _type_name(column.type, dialect):
                errors.append(f"{label}: type differs")
            if actual["nullable"] != column.nullable:
                errors.append(f"{label}: nullable differs")
            default = str(column.server_default.arg) if column.server_default is not None else None
            if actual.get("default") != default:
                errors.append(f"{label}: server default differs")
            if mysql and bool(actual.get("autoincrement", False)) != (table._autoincrement_column is column):
                errors.append(f"{label}: auto increment differs")
            if actual.get("computed") is not None or actual.get("identity") is not None:
                errors.append(f"{label}: unexpected generated value")
        pk = tuple(column.name for column in table.primary_key)
        if tuple(inspector.get_pk_constraint(table.name)["constrained_columns"]) != pk:
            errors.append(f"{prefix}: primary key differs")
        expected_fks = set()
        for fk in table.foreign_key_constraints:
            schema = fk.referred_table.schema
            if schema == current_schema:
                schema = None
            expected_fks.add((tuple(element.parent.name for element in fk.elements), schema,
                              fk.referred_table.name, tuple(element.column.name for element in fk.elements),
                              _action(fk.ondelete), _action(fk.onupdate)))
        actual_fks = {foreign_key_signature(fk, current_schema)
                      for fk in inspector.get_foreign_keys(table.name)}
        if expected_fks != actual_fks:
            errors.append(f"{prefix}: foreign keys differ")
        expected_indexes = {(tuple(column.name for column in index.columns), bool(index.unique))
                            for index in table.indexes}
        if mysql:
            # MySQL exposes UNIQUE constraints as indexes and creates FK support
            # indexes only when no existing PK/secondary left prefix supports it.
            expected_indexes.update((tuple(column.name for column in constraint.columns), True)
                                    for constraint in table.constraints
                                    if isinstance(constraint, UniqueConstraint))
            for fk in table.foreign_key_constraints:
                columns = tuple(element.parent.name for element in fk.elements)
                if pk[:len(columns)] != columns and not any(
                    index_columns[:len(columns)] == columns for index_columns, _ in expected_indexes
                ):
                    expected_indexes.add((columns, False))
        else:
            expected_unique = {tuple(column.name for column in constraint.columns)
                               for constraint in table.constraints
                               if isinstance(constraint, UniqueConstraint)}
            if {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(table.name)} != expected_unique:
                errors.append(f"{prefix}: unique constraints differ")
        indexes = inspector.get_indexes(table.name)
        actual_indexes = {(tuple(index["column_names"]), bool(index["unique"])) for index in indexes}
        if actual_indexes != expected_indexes or len(indexes) != len(expected_indexes):
            errors.append(f"{prefix}: secondary indexes differ")
        if inspector.get_check_constraints(table.name):
            errors.append(f"{prefix}: unexpected CHECK constraint")
        if mysql:
            options = inspector.get_table_options(table.name)
            expected_options = table.dialect_options["mysql"]
            if options.get("mysql_engine", "").lower() != expected_options["engine"].lower():
                errors.append(f"{prefix}: engine differs")
            if options.get("mysql_default charset") != expected_options["charset"]:
                errors.append(f"{prefix}: charset differs")
            if expected_options.get("collate") is not None and options.get("mysql_collate") != expected_options["collate"]:
                errors.append(f"{prefix}: collation differs")
    # Query the marker only if its shape is safe to select. Structural differences
    # already reject the schema; they must not turn into a database SQL error.
    if not errors and connection.execute(select(schema_versions)).all() != [(1, SCHEMA_VERSION)]:
        errors.append("schema_versions: requires only marker (1, current_version)")
    return errors
