-- Aesir AI Service: MySQL 8.4+ schema v1, empty application database only.
-- Generated from SQLAlchemy metadata; check with python -m scripts.check_database_design.
-- No CREATE DATABASE, GRANT, USE, DROP, IF NOT EXISTS, or credential material.
-- DDL auto-commits in MySQL. Stop on the first error; never use mysql --force.
-- Mark v1 only after all eight CREATE TABLE statements have succeeded.

CREATE TABLE access_players (
	game_id VARCHAR(100) NOT NULL,
	player_id VARCHAR(36) NOT NULL,
	active BOOL NOT NULL,
	PRIMARY KEY (game_id, player_id)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE access_quotas (
	game_id VARCHAR(100) NOT NULL,
	player_id VARCHAR(36) NOT NULL,
	kind VARCHAR(20) NOT NULL,
	window_start BIGINT NOT NULL,
	used INTEGER NOT NULL,
	PRIMARY KEY (game_id, player_id, kind, window_start)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE documents (
	namespace VARCHAR(32) NOT NULL,
	key_hash VARCHAR(64) NOT NULL,
	key_parts JSON NOT NULL,
	scope_parts JSON NOT NULL,
	payload JSON NOT NULL,
	version BIGINT NOT NULL,
	PRIMARY KEY (namespace, key_hash)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE operation_journal (
	identity_hash VARCHAR(64) NOT NULL,
	kind VARCHAR(16) NOT NULL,
	key_parts JSON NOT NULL,
	scope_parts JSON NOT NULL,
	request_id VARCHAR(100) NOT NULL,
	fingerprint VARCHAR(64) NOT NULL,
	owner_instance VARCHAR(36) NOT NULL,
	state VARCHAR(16) NOT NULL,
	result JSON,
	error JSON,
	confirmed_version BIGINT,
	created_at DOUBLE NOT NULL,
	finished_at DOUBLE,
	PRIMARY KEY (identity_hash)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE schema_versions (
	id INTEGER NOT NULL AUTO_INCREMENT,
	version INTEGER NOT NULL,
	PRIMARY KEY (id)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE state_versions (
	scope_hash VARCHAR(64) NOT NULL,
	scope_parts JSON NOT NULL,
	version BIGINT NOT NULL,
	PRIMARY KEY (scope_hash)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE access_credentials (
	credential_id VARCHAR(36) NOT NULL,
	game_id VARCHAR(100) NOT NULL,
	player_id VARCHAR(36) NOT NULL,
	secret_hash VARCHAR(64) NOT NULL,
	permissions VARCHAR(250) NOT NULL,
	created_at DOUBLE NOT NULL,
	expires_at DOUBLE NOT NULL,
	revoked BOOL NOT NULL,
	PRIMARY KEY (credential_id),
	FOREIGN KEY(game_id, player_id) REFERENCES access_players (game_id, player_id)
)ENGINE=InnoDB CHARSET=utf8mb4;

CREATE TABLE access_save_grants (
	game_id VARCHAR(100) NOT NULL,
	player_id VARCHAR(36) NOT NULL,
	save_id VARCHAR(36) NOT NULL,
	active BOOL NOT NULL,
	PRIMARY KEY (game_id, player_id, save_id),
	FOREIGN KEY(game_id, player_id) REFERENCES access_players (game_id, player_id)
)ENGINE=InnoDB CHARSET=utf8mb4;

INSERT INTO schema_versions (id, version) VALUES (1, 1);
