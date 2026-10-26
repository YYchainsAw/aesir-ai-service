"""Schema drift must fail before serving SQL traffic or performing implicit DDL."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import DefaultClause, Float, MetaData, event, insert, inspect, text
from sqlalchemy.dialects import mysql

from app.main import app
from app.persistence.database import Database, get_database, reset_database
from app.persistence.schema import SCHEMA_VERSION, schema_versions
from app.persistence import validation
from app.scoped.errors import ScopeError
from scripts import persistence_data


def assert_mismatch(call):
    with pytest.raises(ScopeError) as caught:
        call()
    assert caught.value.status_code == 503
    assert caught.value.code == "DATABASE_SCHEMA_MISMATCH"
    assert caught.value.message == "Application database schema does not match the supported version"


@pytest.fixture
def database(tmp_path):
    database = Database.from_url("sqlite:///" + str(tmp_path / "schema.sqlite"))
    database.initialize_schema()
    yield database
    reset_database()
    database.engine.dispose()


def test_full_schema_is_registered_without_service_imports(database):
    assert len(validation.application_metadata().tables) == 8
    database.check_schema()


@pytest.mark.parametrize("change", ["nullable", "type", "server_default"])
def test_real_sqlite_reflection_rejects_column_drift(tmp_path, change):
    expected = MetaData()
    for table in validation.application_metadata().sorted_tables:
        table.to_metadata(expected)
    column = expected.tables["access_credentials"].c.expires_at
    if change == "nullable":
        column.nullable = True
    elif change == "type":
        column.type = Float()
    else:
        column.server_default = DefaultClause("0")
    database = Database.from_url("sqlite:///" + str(tmp_path / (change + ".sqlite")))
    expected.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.execute(insert(schema_versions).values(id=1, version=SCHEMA_VERSION))
    try:
        assert_mismatch(database.check_schema)
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("statement", [
    "DROP TABLE operation_journal",
    "ALTER TABLE documents ADD COLUMN unexpected INTEGER",
    "CREATE TABLE unrelated (id INTEGER PRIMARY KEY)",
    "CREATE INDEX unexpected ON access_players (active)",
    "UPDATE schema_versions SET version=999",
    "DELETE FROM schema_versions",
    "INSERT INTO schema_versions (id, version) VALUES (2, 1)",
])
def test_real_sqlite_rejects_table_column_index_and_version_drift(database, statement):
    with database.engine.begin() as connection:
        connection.execute(text(statement))
    assert_mismatch(database.check_schema)


def test_existing_valid_init_is_read_only_and_preserves_business_rows(database):
    database.write_document("memory", ("owned",), {"preserved": True})
    statements = []
    event.listen(database.engine, "before_cursor_execute", lambda _c, _cu, statement, _p, _cx, _m: statements.append(statement))
    database.initialize_schema()
    assert not any(statement.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert database.read_document("memory", ("owned",)) == {"preserved": True}


@pytest.mark.parametrize("partial", ["application", "unrelated", "wrong_version"])
def test_init_never_repairs_or_marks_an_existing_schema(tmp_path, partial):
    database = Database.from_url("sqlite:///" + str(tmp_path / (partial + ".sqlite")))
    if partial == "wrong_version":
        database.initialize_schema()
        with database.engine.begin() as connection:
            connection.execute(schema_versions.update().values(version=999))
    else:
        with database.engine.begin() as connection:
            connection.execute(text("CREATE TABLE " + ("schema_versions (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)" if partial == "application" else "unrelated (id INTEGER PRIMARY KEY)")))
    with database.engine.connect() as connection:
        before = inspect(connection).get_table_names()
    statements = []
    event.listen(database.engine, "before_cursor_execute", lambda _c, _cu, statement, _p, _cx, _m: statements.append(statement))
    try:
        assert_mismatch(database.initialize_schema)
        with database.engine.connect() as connection:
            assert inspect(connection).get_table_names() == before
        assert not any(statement.lstrip().upper().startswith(("CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE")) for statement in statements)
    finally:
        database.engine.dispose()


def configured(monkeypatch, path):
    reset_database()
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "sql")
    monkeypatch.setenv("AESIR_SCOPE_DATABASE_URL_FILE", "")
    monkeypatch.setenv("AESIR_SCOPE_DATABASE_URL", "sqlite:///" + str(path))
    monkeypatch.setenv("AESIR_SCOPE_SQLITE_TEST_MODE", "true")


def test_first_sql_access_does_not_cache_a_schema_failure(tmp_path, monkeypatch):
    configured(monkeypatch, tmp_path / "configured.sqlite")
    assert_mismatch(get_database)
    # Operator bootstrap uses a separate uncached connection; a failed first
    # access can then recover rather than retaining an unvalidated object.
    operator = persistence_data.database_for_initialization()
    try:
        operator.initialize_schema()
    finally:
        operator.engine.dispose()
    checked = []
    original = Database.check_schema
    monkeypatch.setattr(Database, "check_schema", lambda db: (checked.append(db), original(db))[1])
    try:
        assert get_database() is get_database()
        assert len(checked) == 1
    finally:
        reset_database()


def test_operator_init_bootstraps_empty_database_but_dry_run_has_no_ddl(tmp_path, monkeypatch, capsys):
    path = tmp_path / "operator.sqlite"
    configured(monkeypatch, path)
    assert persistence_data.main(["init"]) == 0
    assert not path.exists()
    assert persistence_data.main(["init", "--apply"]) == 0
    assert persistence_data.main(["init", "--apply"]) == 0
    try:
        get_database().check_schema()
    finally:
        reset_database()
    assert "schema_version" in capsys.readouterr().out


def test_sql_lifespan_rejects_drift_before_accepting_health_requests(tmp_path, monkeypatch):
    configured(monkeypatch, tmp_path / "startup.sqlite")
    try:
        with pytest.raises(ScopeError) as caught:
            with TestClient(app):
                pytest.fail("A mismatched SQL database must not finish application startup")
        assert caught.value.code == "DATABASE_SCHEMA_MISMATCH"
    finally:
        reset_database()


def test_sql_lifespan_rechecks_an_already_cached_database(tmp_path, monkeypatch):
    configured(monkeypatch, tmp_path / "cached.sqlite")
    operator = persistence_data.database_for_initialization()
    try:
        operator.initialize_schema()
    finally:
        operator.engine.dispose()
    try:
        cached = get_database()
        with cached.engine.begin() as connection:
            connection.execute(text("DROP TABLE operation_journal"))
        # Ordinary lookups retain the one-time cache for request performance;
        # each new application lifespan must nevertheless inspect again.
        assert get_database() is cached
        with pytest.raises(ScopeError) as caught:
            with TestClient(app):
                pytest.fail("A cached database must not bypass the startup gate")
        assert caught.value.code == "DATABASE_SCHEMA_MISMATCH"
    finally:
        reset_database()


def test_json_lifespan_does_not_open_sql_database(tmp_path, monkeypatch):
    path = tmp_path / "unused.sqlite"
    configured(monkeypatch, path)
    monkeypatch.setenv("AESIR_SCOPE_STORAGE_BACKEND", "json")
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
        assert not path.exists()
    finally:
        reset_database()


class ReflectedMySQL:
    """Realistic metadata reflection, including InnoDB-created support indexes."""
    default_schema_name = "application"

    def __init__(self):
        tables = validation.application_metadata().sorted_tables
        self.columns = {table.name: [
            {"name": column.name, "type": column.type, "nullable": column.nullable,
             "default": None, "autoincrement": table._autoincrement_column is column}
            for column in table.c] for table in tables}
        self.pk = {table.name: {"constrained_columns": [column.name for column in table.primary_key]} for table in tables}
        self.fks = {table.name: [
            {"constrained_columns": [element.parent.name for element in fk.elements],
             "referred_schema": None, "referred_table": fk.referred_table.name,
             "referred_columns": [element.column.name for element in fk.elements], "options": {}}
            for fk in table.foreign_key_constraints] for table in tables}
        self.indexes = {table.name: [] for table in tables}
        self.indexes["access_credentials"] = [{"column_names": ["game_id", "player_id"], "unique": False}]
        # operation_journal carries its own operational secondary indexes.
        self.indexes["operation_journal"] = [
            {"column_names": ["state", "created_at"], "unique": False},
            {"column_names": ["request_id"], "unique": False},
        ]
        self.checks = {table.name: [] for table in tables}
        self.options = {table.name: {"mysql_engine": "InnoDB", "mysql_default charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_ai_ci"} for table in tables}
        self.markers = [(1, SCHEMA_VERSION)]

    def get_table_names(self):
        return list(self.columns)

    def get_columns(self, table):
        return self.columns[table]

    def get_pk_constraint(self, table):
        return self.pk[table]

    def get_foreign_keys(self, table):
        return self.fks[table]

    def get_indexes(self, table):
        return self.indexes[table]

    def get_unique_constraints(self, table):
        return []

    def get_check_constraints(self, table):
        return self.checks[table]

    def get_table_options(self, table):
        return self.options[table]


@pytest.fixture
def reflected(monkeypatch):
    reflection = ReflectedMySQL()
    monkeypatch.setattr(validation, "inspect", lambda _connection: reflection)
    connection = SimpleNamespace(dialect=mysql.dialect(), execute=lambda _statement: SimpleNamespace(all=lambda: reflection.markers))
    return reflection, connection


def expiry(reflection):
    return next(column for column in reflection.columns["access_credentials"] if column["name"] == "expires_at")


@pytest.mark.parametrize("change,expected", [
    (lambda r: expiry(r).update(nullable=True), "access_credentials.expires_at: nullable differs"),
    (lambda r: expiry(r).update(type=Float()), "access_credentials.expires_at: type differs"),
    (lambda r: expiry(r).update(default="0"), "access_credentials.expires_at: server default differs"),
    (lambda r: expiry(r).update(type=mysql.DOUBLE(unsigned=True)), "access_credentials.expires_at: type differs"),
    (lambda r: r.columns["schema_versions"][0].update(autoincrement=False), "schema_versions.id: auto increment differs"),
    (lambda r: r.columns["documents"].reverse(), "documents: column names/order differ"),
    (lambda r: r.pk["access_credentials"].update(constrained_columns=["game_id", "player_id"]), "access_credentials: primary key differs"),
    (lambda r: r.fks["access_credentials"][0].update(referred_schema="another_database"), "access_credentials: foreign keys differ"),
    (lambda r: r.fks["access_save_grants"].clear(), "access_save_grants: foreign keys differ"),
    (lambda r: r.fks["access_credentials"][0].update(options={"ondelete": "CASCADE"}), "access_credentials: foreign keys differ"),
    (lambda r: r.indexes["access_credentials"].clear(), "access_credentials: secondary indexes differ"),
    (lambda r: r.indexes["access_credentials"][0].update(unique=True), "access_credentials: secondary indexes differ"),
    (lambda r: r.indexes["access_credentials"].append(deepcopy(r.indexes["access_credentials"][0])), "access_credentials: secondary indexes differ"),
    (lambda r: r.options["documents"].update(mysql_engine="MyISAM"), "documents: engine differs"),
    (lambda r: r.options["documents"].update({"mysql_default charset": "latin1"}), "documents: charset differs"),
    (lambda r: r.checks["access_players"].append({"sqltext": "active=1"}), "access_players: unexpected CHECK constraint"),
    (lambda r: expiry(r).update(computed={"sqltext": "0"}), "access_credentials.expires_at: unexpected generated value"),
    (lambda r: r.markers.append((2, 1)), "schema_versions: requires only marker (1, current_version)"),
])
def test_mysql_shared_gate_rejects_unsafe_structure_changes(reflected, change, expected):
    reflection, connection = reflected
    assert validation.schema_differences(connection) == []
    change(reflection)
    assert expected in validation.schema_differences(connection)


def test_mysql_accepts_same_schema_fk_alias_and_does_not_invent_collation_requirement(reflected):
    reflection, connection = reflected
    reflection.fks["access_credentials"][0].update(referred_schema="application", options={"ondelete": "NO ACTION"})
    reflection.options["documents"]["mysql_collate"] = "utf8mb4_bin"
    reflection.columns["access_players"][-1]["type"] = mysql.TINYINT(display_width=1)
    assert validation.schema_differences(connection) == []
