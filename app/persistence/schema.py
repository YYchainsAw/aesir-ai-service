"""Explicitly migrated application tables; HTTP requests never create schema."""
from sqlalchemy import BigInteger, Column, Integer, JSON, MetaData, String, Table

SCHEMA_VERSION = 1
metadata = MetaData()

schema_versions = Table(
    "schema_versions", metadata,
    Column("id", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
documents = Table(
    "documents", metadata,
    Column("namespace", String(32), primary_key=True),
    Column("key_hash", String(64), primary_key=True),
    Column("key_parts", JSON, nullable=False),
    Column("scope_parts", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("version", BigInteger, nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
state_versions = Table(
    "state_versions", metadata,
    Column("scope_hash", String(64), primary_key=True),
    Column("scope_parts", JSON, nullable=False),
    Column("version", BigInteger, nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)
