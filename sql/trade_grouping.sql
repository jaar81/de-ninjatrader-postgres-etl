CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE VIEW analytics.grouped_trades AS

WITH valid_trades AS (
    SELECT *
    FROM core.trades
    WHERE entry_time IS NOT NULL
      AND exit_time IS NOT NULL
      AND exit_time >= entry_time
	ORDER BY trade_number
),

-- Step 1: Treat entries at the same timestamp
-- and direction as a single batch.
entry_batches AS (
    SELECT
        market_position,
        entry_time,
        MAX(exit_time) AS batch_max_exit
    FROM valid_trades
    GROUP BY
        market_position,
        entry_time
),

-- Step 2: Find the latest exit across ALL
-- earlier entry batches in this direction.
timeline AS (
    SELECT
        *,
        MAX(batch_max_exit) OVER (
            PARTITION BY market_position
            ORDER BY entry_time
            ROWS BETWEEN UNBOUNDED PRECEDING
                     AND 1 PRECEDING
        ) AS previous_max_exit
    FROM entry_batches
),

-- Step 3: Flag where a new group begins.
flagged AS (
    SELECT
        *,
        CASE
            WHEN previous_max_exit IS NULL
              OR entry_time >= previous_max_exit
            THEN 1
            ELSE 0
        END AS new_group_flag
    FROM timeline
),

-- Step 4: Number groups using cumulative SUM.
numbered AS (
    SELECT
        *,
        SUM(new_group_flag) OVER (
            PARTITION BY market_position
            ORDER BY entry_time
            ROWS BETWEEN UNBOUNDED PRECEDING
                     AND CURRENT ROW
        ) AS group_number
    FROM flagged
),

-- Step 5: Calculate each group's first entry.
with_group_start AS (
    SELECT
        *,
        MIN(entry_time) OVER (
            PARTITION BY market_position, group_number
        ) AS group_start_time
    FROM numbered
)

-- Step 6: Attach the group to every original row.

SELECT
    t.*,

    -- Unique group number across Long and Short
    DENSE_RANK() OVER (
        ORDER BY
            g.group_start_time,
            t.market_position
    ) AS group_number,

    g.group_start_time,

    t.market_position || '_' ||
    TO_CHAR(
        g.group_start_time,
        'YYYYMMDDHH24MISSUS'
    ) AS trade_group_key,

    -- Keep the original per-direction number
    g.group_number AS direction_group_number

FROM valid_trades t

JOIN with_group_start g
  ON t.market_position = g.market_position
 AND t.entry_time = g.entry_time;
