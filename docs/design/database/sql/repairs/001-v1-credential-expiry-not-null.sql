-- Repair an observed v1 drift, not a schema v2 migration.
-- MySQL 8.4+ only; run with the scoped migrator in batch mode, never --force.
-- The procedure guards the ALTER itself. No existing application database is
-- repaired automatically by the application or by the design checker.
-- DDL auto-commits. A failed CALL leaves the helper for operator inspection.

DELIMITER $$

CREATE PROCEDURE aesir_repair_v1_credential_expiry_not_null()
SQL SECURITY INVOKER
BEGIN
    IF (SELECT COUNT(*) FROM schema_versions) <> 1
       OR (SELECT COUNT(*) FROM schema_versions WHERE id = 1 AND version = 1) <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Repair requires the single schema v1 marker';
    END IF;

    IF (SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'access_credentials'
          AND COLUMN_NAME = 'expires_at'
          AND DATA_TYPE = 'double') <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Repair requires a DOUBLE expires_at column';
    END IF;

    IF (SELECT COUNT(*) FROM access_credentials WHERE expires_at IS NULL) <> 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Repair blocked: review NULL expiry rows before changing schema';
    END IF;

    ALTER TABLE access_credentials MODIFY COLUMN expires_at DOUBLE NOT NULL;
END$$

CALL aesir_repair_v1_credential_expiry_not_null()$$
DROP PROCEDURE aesir_repair_v1_credential_expiry_not_null$$

DELIMITER ;
