-- Fresh-database bootstrap. See docs/implementation_notes.md before using an
-- existing trading database. No existing objects are dropped or migrated.
BEGIN;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS control;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;
COMMIT;
