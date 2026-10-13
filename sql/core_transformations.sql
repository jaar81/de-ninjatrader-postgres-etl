-- REFERENCE ONLY: this is the actual INSERT executed inside src/load_trades.py.
-- The loader supplies the file hash for the Psycopg %s parameter.
-- Do not run this file with psql; no separate transformation setup is needed.
-- Edit the Python loader if the transformation is deliberately changed.

INSERT INTO core.trades (
    trade_number,
    instrument,
    account,
    strategy,
    market_position,
    qty,
    entry_price,
    exit_price,
    entry_time,
    exit_time,
    entry_name,
    exit_name,
    profit,
    cumulative_net_profit,
    commission,
    mae,
    mfe,
    etd,
    bars,
    source_file,
    source_file_hash,
    source_row_number,
    loaded_at
)

SELECT


    -- =============================================
    -- TRADE NUMBER
    -- =============================================

    NULLIF(
        TRIM(trade_number),
        ''
    )::INTEGER,


    -- =============================================
    -- TEXT FIELDS
    -- =============================================

    NULLIF(TRIM(instrument), ''),
    NULLIF(TRIM(account), ''),
    NULLIF(TRIM(strategy), ''),
    NULLIF(TRIM(market_position), ''),


    -- =============================================
    -- QUANTITY
    -- =============================================

    NULLIF(
        TRIM(qty),
        ''
    )::INTEGER,


    -- =============================================
    -- ENTRY PRICE
    -- =============================================
    --
    -- Example:
    --
    -- $19,829.00
    --
    -- becomes:
    --
    -- 19829.00

    NULLIF(
        REGEXP_REPLACE(
            entry_price,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- EXIT PRICE
    -- =============================================

    NULLIF(
        REGEXP_REPLACE(
            exit_price,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- ENTRY TIME
    -- =============================================
    --
    -- NinjaTrader exports may contain either:
    --
    -- 12-hour format:
    --
    -- 9/3/2024 3:26:17 AM
    --
    -- or 24-hour format:
    --
    -- 11/06/2025 14:35:00
    --
    -- If the value ends with AM or PM, parse it
    -- using HH12.
    --
    -- Otherwise use HH24.

    CASE

        WHEN TRIM(entry_time) ~* '(AM|PM)$'

        THEN TO_TIMESTAMP(
            TRIM(entry_time),
            'MM/DD/YYYY HH12:MI:SS AM'
        )::TIMESTAMP

        ELSE TO_TIMESTAMP(
            TRIM(entry_time),
            'MM/DD/YYYY HH24:MI:SS'
        )::TIMESTAMP

    END,


    -- =============================================
    -- EXIT TIME
    -- =============================================

    CASE

        WHEN TRIM(exit_time) ~* '(AM|PM)$'

        THEN TO_TIMESTAMP(
            TRIM(exit_time),
            'MM/DD/YYYY HH12:MI:SS AM'
        )::TIMESTAMP

        ELSE TO_TIMESTAMP(
            TRIM(exit_time),
            'MM/DD/YYYY HH24:MI:SS'
        )::TIMESTAMP

    END,


    -- =============================================
    -- ENTRY / EXIT NAME
    -- =============================================

    NULLIF(TRIM(entry_name), ''),
    NULLIF(TRIM(exit_name), ''),


    -- =============================================
    -- PROFIT
    -- =============================================
    --
    -- NinjaTrader uses accounting-style
    -- parentheses for losses.
    --
    -- Examples:
    --
    -- $74.78
    -- becomes
    -- 74.78
    --
    -- ($74.78)
    -- becomes
    -- -74.78
    --
    -- ($1,250.50)
    -- becomes
    -- -1250.50
    --
    -- This regex:
    --
    -- ^\(.*\)$
    --
    -- means:
    --
    -- Starts with (
    -- contains anything
    -- ends with )

    CASE

        WHEN TRIM(profit) ~ '^\(.*\)$'

        THEN
            -1 * NULLIF(
                REGEXP_REPLACE(
                    profit,
                    '[$,()]',
                    '',
                    'g'
                ),
                ''
            )::NUMERIC(18, 2)

        ELSE
            NULLIF(
                REGEXP_REPLACE(
                    profit,
                    '[$,()]',
                    '',
                    'g'
                ),
                ''
            )::NUMERIC(18, 2)

    END,


    -- =============================================
    -- CUMULATIVE NET PROFIT
    -- =============================================
    --
    -- Same accounting-negative logic as Profit.

    CASE

        WHEN TRIM(cumulative_net_profit)
             ~ '^\(.*\)$'

        THEN
            -1 * NULLIF(
                REGEXP_REPLACE(
                    cumulative_net_profit,
                    '[$,()]',
                    '',
                    'g'
                ),
                ''
            )::NUMERIC(18, 2)

        ELSE
            NULLIF(
                REGEXP_REPLACE(
                    cumulative_net_profit,
                    '[$,()]',
                    '',
                    'g'
                ),
                ''
            )::NUMERIC(18, 2)

    END,


    -- =============================================
    -- COMMISSION
    -- =============================================

    NULLIF(
        REGEXP_REPLACE(
            commission,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- MAE
    -- =============================================

    NULLIF(
        REGEXP_REPLACE(
            mae,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- MFE
    -- =============================================

    NULLIF(
        REGEXP_REPLACE(
            mfe,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- ETD
    -- =============================================

    NULLIF(
        REGEXP_REPLACE(
            etd,
            '[$,]',
            '',
            'g'
        ),
        ''
    )::NUMERIC(18, 2),


    -- =============================================
    -- BARS
    -- =============================================

    NULLIF(
        TRIM(bars),
        ''
    )::INTEGER,


    -- =============================================
    -- PIPELINE METADATA
    -- =============================================

    source_file,
    source_file_hash,
    source_row_number,
    loaded_at


FROM raw.ninjatrader_trades


-- Only transform rows belonging to the file
-- currently being processed.

WHERE source_file_hash = %s


-- The UNIQUE constraint on:
--
-- source_file_hash
-- source_row_number
--
-- prevents the exact same source row from being
-- inserted twice.

ON CONFLICT (
    source_file_hash,
    source_row_number
)
DO NOTHING;
