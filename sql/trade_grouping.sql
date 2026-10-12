-- OPTIONAL / EXPERIMENTAL. Run only after core_transformations.sql.
-- This creates review candidates, not an authoritative grouped-trade model.
-- The full final historical SQL was unavailable. See docs/trade_grouping.md.
-- It deliberately does not replace or create analytics.grouped_trades.
-- Confirmed intent: the current original A-E batch must fully close before
-- the next original batch in that direction; later C/D/E scale-ins attach to
-- their original batch. Rolling interval overlap does not prove these rules.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.trade_group_candidates AS
WITH valid_trades AS (
    SELECT *
    FROM core.trades
    WHERE entry_time IS NOT NULL
      AND exit_time IS NOT NULL
      AND exit_time >= entry_time
),
-- Recovered approach: rows at the same timestamp and direction form a batch.
-- NEW scope assumption: also isolate file hash/account/instrument/strategy.
-- This avoids mixing those streams; it does not deduplicate overlapping files.
entry_batches AS (
    SELECT
        source_file_hash,
        account,
        instrument,
        strategy,
        market_position,
        entry_time,
        MAX(exit_time) AS batch_max_exit
    FROM valid_trades
    GROUP BY source_file_hash, account, instrument, strategy,
             market_position, entry_time
),
timeline AS (
    SELECT
        *,
        MAX(batch_max_exit) OVER (
            PARTITION BY source_file_hash, account, instrument, strategy,
                         market_position
            ORDER BY entry_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_max_exit
    FROM entry_batches
),
-- RECONSTRUCTED continuation; this CASE was not available in the source.
-- ASSUMPTION: strictly later entry starts a new candidate. Equality merges
-- provisionally and is flagged below. Null/invalid times are excluded above.
flagged AS (
    SELECT
        *,
        CASE
            WHEN previous_max_exit IS NULL OR entry_time > previous_max_exit
            THEN 1 ELSE 0
        END AS starts_candidate_group
    FROM timeline
),
numbered AS (
    SELECT
        *,
        SUM(starts_candidate_group) OVER (
            PARTITION BY source_file_hash, account, instrument, strategy,
                         market_position
            ORDER BY entry_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS group_number
    FROM flagged
),
candidate_batches AS (
    SELECT
        *,
        MIN(entry_time) OVER (
            PARTITION BY source_file_hash, account, instrument, strategy,
                         market_position, group_number
        ) AS group_start_time
    FROM numbered
)
SELECT
    t.*,
    -- Diagnostic labels only. An A name alone cannot establish a new trade:
    -- repeated A rows may describe multiple exits from one original entry.
    CASE
        WHEN t.entry_name ILIKE '%scal%' THEN 'scale_candidate'
        WHEN t.entry_name ~* '^((.*[[:space:]])?entry[[:space:]]+)?A[[:space:]]*$'
            THEN 'entry_a_candidate'
        WHEN t.entry_name ~* '^((.*[[:space:]])?entry[[:space:]]+)?[B-E][[:space:]]*$'
            THEN 'named_entry_candidate'
        ELSE 'other_or_unknown'
    END AS entry_kind,
    b.batch_max_exit,
    b.previous_max_exit,
    b.starts_candidate_group,
    -- This is LOCAL to the full partition above, never a global trade ID.
    b.group_number,
    b.group_start_time,
    COALESCE(t.entry_time = b.previous_max_exit, FALSE)
        AS equal_boundary_requires_review,
    COALESCE(
        t.entry_name ~* '^((.*[[:space:]])?entry[[:space:]]+)?A[[:space:]]*$'
        AND t.entry_time > b.group_start_time,
        FALSE
    ) AS later_a_requires_review,
    'experimental_unverified'::text AS grouping_status
FROM valid_trades AS t
JOIN candidate_batches AS b
  ON t.source_file_hash IS NOT DISTINCT FROM b.source_file_hash
 AND t.account IS NOT DISTINCT FROM b.account
 AND t.instrument IS NOT DISTINCT FROM b.instrument
 AND t.strategy IS NOT DISTINCT FROM b.strategy
 AND t.market_position IS NOT DISTINCT FROM b.market_position
 AND t.entry_time = b.entry_time;

COMMENT ON VIEW analytics.trade_group_candidates IS
    'Experimental reconstructed time-overlap grouping; not validated against '
    'the reported A/scale-in case. group_number is local to file/account/'
    'instrument/strategy/direction. Do not use for official trade metrics.';

-- Review queries are comments so setup only creates the optional view.
-- First inspect rows excluded by the candidate algorithm:
-- SELECT trade_id, entry_name, entry_time, exit_time,
--        source_file, source_row_number
-- FROM core.trades
-- WHERE entry_time IS NULL OR exit_time IS NULL OR exit_time < entry_time
-- ORDER BY source_file_hash, source_row_number;

-- Inspect candidate membership and flags; group_number alone is not unique:
-- SELECT source_file_hash, account, instrument, strategy, market_position,
--        group_number, group_start_time, entry_time, exit_time, entry_name,
--        entry_kind, later_a_requires_review, equal_boundary_requires_review,
--        source_row_number
-- FROM analytics.trade_group_candidates
-- ORDER BY source_file_hash, account, instrument, strategy, market_position,
--          group_start_time, entry_time, source_row_number;
