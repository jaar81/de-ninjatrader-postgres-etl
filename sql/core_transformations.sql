-- Reconstructed from the latest loader and HH12/HH24 patch.
-- The original inline INSERT is factored into a function so the loader and
-- SQL users share one transformation. Strict format validation is new here.
BEGIN;

CREATE OR REPLACE FUNCTION core.parse_money(
    input_value text, allow_accounting boolean DEFAULT true
) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE
    value text := btrim(input_value);
    negative boolean := false;
BEGIN
    IF value IS NULL OR value = '' THEN RETURN NULL; END IF;
    IF left(value, 1) = '(' AND right(value, 1) = ')' THEN
        IF NOT allow_accounting THEN
            RAISE EXCEPTION 'Accounting parentheses are not supported for this field';
        END IF;
        negative := true;
        value := btrim(substr(value, 2, length(value) - 2));
        -- Do not turn an already negative value positive (e.g. (-10)).
        IF value ~ '[+-]' THEN
            RAISE EXCEPTION 'Conflicting accounting sign';
        END IF;
    END IF;
    -- US dollar exports only. Reject malformed punctuation instead of silently
    -- turning e.g. 12,34 into 1234. Exponents/NaN/Infinity are not trade values.
    IF value !~ '^([-+]?[$]?|[$][-+]?)([0-9]+([.][0-9]*)?|[0-9]{1,3}(,[0-9]{3})+([.][0-9]*)?|[.][0-9]+)$' THEN
        RAISE EXCEPTION 'Invalid numeric format';
    END IF;
    value := replace(replace(value, '$', ''), ',', '');
    RETURN CASE WHEN negative THEN -value::numeric ELSE value::numeric END;
END
$fn$;

CREATE OR REPLACE FUNCTION core.parse_trade_timestamp(input_value text)
RETURNS timestamp without time zone
LANGUAGE plpgsql STABLE SET TimeZone = 'UTC' AS $fn$
DECLARE
    value text := upper(btrim(input_value));
    parts text[];
    parsed timestamp;
    hour_value integer;
BEGIN
    IF value IS NULL OR value = '' THEN RETURN NULL; END IF;
    parts := regexp_match(value,
        '^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4}) ([0-9]{1,2}):([0-9]{2}):([0-9]{2})( (AM|PM))?$');
    IF parts IS NULL THEN RAISE EXCEPTION 'Unsupported timestamp format'; END IF;
    hour_value := parts[4]::integer;
    IF parts[5]::integer > 59 OR parts[6]::integer > 59 THEN
        RAISE EXCEPTION 'Invalid minute or second';
    END IF;
    IF parts[8] IS NOT NULL THEN
        IF hour_value NOT BETWEEN 1 AND 12 THEN
            RAISE EXCEPTION 'Invalid 12-hour time';
        END IF;
        parsed := to_timestamp(value, 'MM/DD/YYYY HH12:MI:SS AM')::timestamp;
    ELSE
        IF hour_value NOT BETWEEN 0 AND 23 THEN
            RAISE EXCEPTION 'Invalid 24-hour time';
        END IF;
        parsed := to_timestamp(value, 'MM/DD/YYYY HH24:MI:SS')::timestamp;
    END IF;
    -- Guard against normalization of invalid dates. UTC here only ensures
    -- session DST settings do not alter wall-clock values: NO timezone is
    -- inferred for the source timestamps or added to the returned value.
    IF extract(year FROM parsed) <> parts[3]::integer
       OR extract(month FROM parsed) <> parts[1]::integer
       OR extract(day FROM parsed) <> parts[2]::integer THEN
        RAISE EXCEPTION 'Invalid calendar date';
    END IF;
    RETURN parsed;
END
$fn$;

CREATE OR REPLACE FUNCTION core.load_trades(p_file_hash text)
RETURNS bigint
LANGUAGE plpgsql AS $fn$
DECLARE
    inserted_rows bigint;
BEGIN
    INSERT INTO core.trades (
        trade_number, instrument, account, strategy, market_position, qty,
        entry_price, exit_price, entry_time, exit_time, entry_name, exit_name,
        profit, cumulative_net_profit, commission, mae, mfe, etd, bars,
        source_file, source_file_hash, source_row_number, loaded_at
    )
    SELECT
        nullif(btrim(trade_number), '')::integer,
        nullif(btrim(instrument), ''),
        nullif(btrim(account), ''),
        nullif(btrim(strategy), ''),
        nullif(btrim(market_position), ''),
        nullif(btrim(qty), '')::integer,
        core.parse_money(entry_price, false)::numeric(18, 2),
        core.parse_money(exit_price, false)::numeric(18, 2),
        core.parse_trade_timestamp(entry_time),
        core.parse_trade_timestamp(exit_time),
        nullif(btrim(entry_name), ''),
        nullif(btrim(exit_name), ''),
        core.parse_money(profit)::numeric(18, 2),
        core.parse_money(cumulative_net_profit)::numeric(18, 2),
        core.parse_money(commission, false)::numeric(18, 2),
        core.parse_money(mae, false)::numeric(18, 2),
        core.parse_money(mfe, false)::numeric(18, 2),
        core.parse_money(etd, false)::numeric(18, 2),
        nullif(btrim(bars), '')::integer,
        source_file, source_file_hash, source_row_number, loaded_at
    FROM raw.ninjatrader_trades
    WHERE source_file_hash = p_file_hash
    ON CONFLICT (source_file_hash, source_row_number) DO NOTHING;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END
$fn$;

COMMENT ON FUNCTION core.load_trades(text) IS
    'Transform one raw file hash; caller controls transaction and audit record.';
COMMIT;
