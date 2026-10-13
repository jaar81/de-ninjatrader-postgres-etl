-- Read-only queries using the supplied analytics.grouped_trades view.
-- Grouping is still being validated. It partitions by direction only;
-- unrelated accounts/instruments/strategies/files can share a group.
-- Profit is used as exported; commission is reported separately.

-- Successful loads and row counts.
SELECT source_file, file_hash, raw_row_count, core_row_count, loaded_at
FROM control.file_loads
ORDER BY loaded_at;

-- Inspect every execution with its assigned group. An outer ORDER BY makes
-- the display order explicit rather than relying on the view's inner CTE.
SELECT group_number, trade_group_key, direction_group_number,
       group_start_time, trade_number, market_position, entry_name,
       entry_time, exit_time, qty, profit,
       source_file, source_row_number
FROM analytics.grouped_trades
ORDER BY group_number, entry_time, trade_number, source_file_hash, source_row_number;

-- Provisional group summaries for review, not validated business-trade metrics.
-- Scope counts expose groups containing multiple streams or files.
SELECT group_number, trade_group_key, group_start_time, market_position,
       count(*) AS execution_rows,
       sum(qty) AS reported_quantity_sum,
       min(entry_time) AS first_entry,
       max(exit_time) AS last_exit,
       sum(profit) AS total_exported_profit,
       sum(commission) AS reported_commission,
       count(DISTINCT account) AS account_count,
       count(DISTINCT instrument) AS instrument_count,
       count(DISTINCT strategy) AS strategy_count,
       count(DISTINCT source_file_hash) AS source_file_count
FROM analytics.grouped_trades
GROUP BY group_number, trade_group_key, group_start_time, market_position
ORDER BY group_number;

-- Execution-level summary by file, strategy and direction.
-- Keep files separate: SHA-256 does not deduplicate overlapping exports.
SELECT source_file, source_file_hash, strategy, market_position,
       count(*) AS execution_rows,
       sum(profit) AS total_exported_profit,
       sum(commission) AS reported_commission
FROM core.trades
GROUP BY source_file, source_file_hash, strategy, market_position
ORDER BY source_file_hash, strategy, market_position;

-- Records excluded by the supplied view's time filter or direction join.
SELECT trade_number, market_position, entry_time, exit_time,
       source_file, source_row_number
FROM core.trades
WHERE entry_time IS NULL OR exit_time IS NULL OR exit_time < entry_time
   OR market_position IS NULL
ORDER BY source_file_hash, source_row_number;
