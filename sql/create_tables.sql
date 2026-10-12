-- Reconstructed DDL: original CREATE TABLE statements were not available.
-- Names, source columns and core types follow the recovered working loader.
-- Run once in a NEW database. Deliberately fail if a table already exists;
-- IF NOT EXISTS would hide an incompatible pre-existing table definition.
BEGIN;

CREATE TABLE control.file_loads (
    file_hash text PRIMARY KEY CHECK (file_hash ~ '^[0-9a-f]{64}$'),
    source_file text NOT NULL,
    raw_row_count bigint NOT NULL CHECK (raw_row_count >= 0),
    core_row_count bigint NOT NULL CHECK (core_row_count >= 0),
    loaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE raw.ninjatrader_trades (
    raw_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_number text,
    instrument text,
    account text,
    strategy text,
    market_position text,
    qty text,
    entry_price text,
    exit_price text,
    entry_time text,
    exit_time text,
    entry_name text,
    exit_name text,
    profit text,
    cumulative_net_profit text,
    commission text,
    mae text,
    mfe text,
    etd text,
    bars text,
    source_file text NOT NULL,
    source_file_hash text NOT NULL CHECK (source_file_hash ~ '^[0-9a-f]{64}$'),
    source_row_number bigint NOT NULL CHECK (source_row_number >= 2),
    loaded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_file_hash, source_row_number)
);

CREATE TABLE core.trades (
    trade_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trade_number integer,
    instrument text,
    account text,
    strategy text,
    market_position text,
    qty integer,
    entry_price numeric(18, 2),
    exit_price numeric(18, 2),
    entry_time timestamp without time zone,
    exit_time timestamp without time zone,
    entry_name text,
    exit_name text,
    profit numeric(18, 2),
    cumulative_net_profit numeric(18, 2),
    commission numeric(18, 2),
    mae numeric(18, 2),
    mfe numeric(18, 2),
    etd numeric(18, 2),
    bars integer,
    source_file text NOT NULL,
    source_file_hash text NOT NULL CHECK (source_file_hash ~ '^[0-9a-f]{64}$'),
    source_row_number bigint NOT NULL CHECK (source_row_number >= 2),
    loaded_at timestamptz NOT NULL,
    UNIQUE (source_file_hash, source_row_number)
);

CREATE INDEX trades_entry_time_idx ON core.trades (entry_time);
CREATE INDEX trades_strategy_idx ON core.trades (strategy, instrument);

COMMENT ON TABLE control.file_loads IS
    'Successful loads only; committed atomically with raw and core rows.';
COMMENT ON TABLE raw.ninjatrader_trades IS
    'CSV field values retained as text; not a byte-for-byte archive of the CSV.';
COMMENT ON TABLE core.trades IS
    'Typed execution records, not completed logical trade groups.';
COMMIT;
