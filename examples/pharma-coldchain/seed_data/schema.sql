-- Pharma Cold-Chain Seed Data Schema
-- SQLite-compatible DDL for the pharma cold-chain example.
--
-- Tables: batches, hubs, hub_qualifications, shipments, telemetry_log
-- All timestamps use TEXT (SQLite has no native TIMESTAMP type).

-- Enable foreign key enforcement (SQLite requires this pragma per-connection).
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- hubs: Regional distribution centres with capacity and qualification status.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hubs (
    id              INTEGER PRIMARY KEY,
    name            TEXT    UNIQUE NOT NULL,
    country         TEXT    NOT NULL,
    capacity_doses  INTEGER NOT NULL,
    qualified       BOOLEAN DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- batches: Individual vaccine batches tracked through the cold chain.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS batches (
    id              INTEGER PRIMARY KEY,
    batch_id        TEXT    UNIQUE NOT NULL,
    hub_id          INTEGER REFERENCES hubs(id),
    status          TEXT    DEFAULT 'active',
    temperature_c   REAL,
    humidity_pct    REAL,
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- hub_qualifications: Regulatory qualifications per hub (GDP, GMP, etc.).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hub_qualifications (
    id                  INTEGER PRIMARY KEY,
    hub_id              INTEGER REFERENCES hubs(id),
    qualification_type  TEXT    NOT NULL,
    valid_until         TEXT
);

-- ---------------------------------------------------------------------------
-- shipments: Batch movements between hubs with status tracking.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipments (
    id          INTEGER PRIMARY KEY,
    batch_id    TEXT    REFERENCES batches(batch_id),
    from_hub_id INTEGER,
    to_hub_id   INTEGER,
    status      TEXT    DEFAULT 'pending'
);

-- ---------------------------------------------------------------------------
-- telemetry_log: IoT temperature/humidity readings per batch.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry_log (
    id              INTEGER PRIMARY KEY,
    batch_id        TEXT,
    temperature_c   REAL,
    humidity_pct    REAL,
    recorded_at     TEXT    DEFAULT (datetime('now'))
);
