-- Execution-level analysis only. Grouping is experimental and deliberately
-- excluded. Profit is used AS EXPORTED; whether commissions were included in
-- the export is unknown. Do not subtract commissions again without checking.
-- Do not sum cumulative_net_profit: it is a running value within an export.
-- Different/overlapping exports can contain the same underlying executions.
-- Scope reports to a known, non-overlapping selection of source_file_hashes.

-- File reconciliation. Expected: both differences are zero.
WITH raw_counts AS (
    SELECT source_file_hash, count(*) AS rows FROM raw.ninjatrader_trades
    GROUP BY source_file_hash
), core_counts AS (
    SELECT source_file_hash, count(*) AS rows FROM core.trades
    GROUP BY source_file_hash
)
SELECT f.source_file, f.file_hash, f.loaded_at, f.raw_row_count, f.core_row_count,
       coalesce(r.rows, 0) - f.raw_row_count AS raw_difference,
       coalesce(c.rows, 0) - f.core_row_count AS core_difference
FROM control.file_loads f
LEFT JOIN raw_counts r ON r.source_file_hash = f.file_hash
LEFT JOIN core_counts c ON c.source_file_hash = f.file_hash
ORDER BY f.loaded_at;

-- Strategy/direction summary by file. Unknown profits are counted separately;
-- a missing profit does not get treated as a losing execution.
SELECT source_file, source_file_hash, strategy, instrument, market_position,
       count(*) AS execution_rows,
       count(profit) AS rows_with_profit,
       count(*) FILTER (WHERE profit IS NULL) AS rows_missing_profit,
       sum(profit) AS total_exported_profit,
       sum(commission) AS reported_commission,
       round(100.0 * count(*) FILTER (WHERE profit > 0)
           / nullif(count(profit), 0), 2) AS profitable_execution_pct,
       avg(profit) AS average_exported_profit
FROM core.trades
GROUP BY source_file, source_file_hash, strategy, instrument, market_position
ORDER BY source_file_hash, strategy, instrument, market_position;

-- Daily realized (exit-day) exported profit. No source timezone assumed.
SELECT source_file_hash, exit_time::date AS exit_date, strategy,
       count(*) AS execution_rows, sum(profit) AS total_exported_profit
FROM core.trades
WHERE exit_time IS NOT NULL
GROUP BY source_file_hash, exit_time::date, strategy
ORDER BY source_file_hash, exit_date, strategy;

-- Data-quality review before analytics or grouping.
SELECT source_file, source_row_number, trade_number, entry_name,
       market_position, qty, entry_time, exit_time
FROM core.trades
WHERE entry_time IS NULL OR exit_time IS NULL OR exit_time < entry_time
   OR qty IS NULL OR qty <= 0 OR market_position IS NULL
ORDER BY source_file_hash, source_row_number;
