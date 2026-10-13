import csv
import hashlib
import os
import sys
from pathlib import Path

import psycopg


# ============================================================
# EXPECTED CSV STRUCTURE
# ============================================================

EXPECTED_COLUMNS = [
    "Trade number",
    "Instrument",
    "Account",
    "Strategy",
    "Market pos.",
    "Qty",
    "Entry price",
    "Exit price",
    "Entry time",
    "Exit time",
    "Entry name",
    "Exit name",
    "Profit",
    "Cum. net profit",
    "Commission",
    "MAE",
    "MFE",
    "ETD",
    "Bars",
]


# ============================================================
# CALCULATE FILE HASH
# ============================================================

def calculate_file_hash(file_path: Path) -> str:
    """
    Calculate the SHA-256 hash of a file.

    The hash identifies the file by its contents rather than
    by its filename.

    This means:

        trades.csv
        trades_copy.csv

    will have the same hash if their contents are identical.
    """

    # Create an empty SHA-256 hashing object.
    sha256 = hashlib.sha256()

    # Open the file in binary mode because hashing works
    # with bytes.
    with file_path.open("rb") as file:

        # Read the file 8192 bytes at a time.
        #
        # This prevents us from loading the entire file
        # into memory just to calculate its hash.
        for chunk in iter(lambda: file.read(8192), b""):

            # Add this chunk to the ongoing hash calculation.
            sha256.update(chunk)

    # Return the completed hash as a hexadecimal string.
    return sha256.hexdigest()


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection():
    """
    Create and return a PostgreSQL connection.

    Connection settings are read from environment variables.

    Expected variables:

        PGHOST
        PGPORT
        PGDATABASE
        PGUSER
        PGPASSWORD

    Defaults are supplied for everything except the password.
    """

    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "trading_lab"),
        user=os.getenv("PGUSER", "postgres"),

        # Using os.environ[] means Python will immediately
        # raise an error if PGPASSWORD does not exist.
        password=os.environ["PGPASSWORD"],
    )


# ============================================================
# LOAD ONE CSV FILE
# ============================================================

def load_file(file_path: Path) -> None:
    """
    Load one NinjaTrader CSV file into PostgreSQL.

    Pipeline:

        NinjaTrader CSV
                |
                v
        Validate / identify file
                |
                v
        raw.ninjatrader_trades
                |
                v
        SQL transformation
                |
                v
        core.trades
                |
                v
        control.file_loads


    The entire database operation occurs inside one transaction.

    If everything succeeds:
        COMMIT

    If anything fails:
        ROLLBACK
    """

    # ========================================================
    # CHECK THAT THE FILE EXISTS
    # ========================================================

    if not file_path.exists():

        raise FileNotFoundError(
            f"File does not exist: {file_path}"
        )


    # ========================================================
    # CALCULATE FILE HASH
    # ========================================================

    file_hash = calculate_file_hash(file_path)

    print(f"Processing: {file_path.name}")
    print(f"SHA-256:    {file_hash}")


    # ========================================================
    # OPEN DATABASE CONNECTION / START TRANSACTION
    # ========================================================
    #
    # Psycopg treats this connection context as a transaction.
    #
    # If the block completes:
    #     COMMIT
    #
    # If an exception occurs:
    #     ROLLBACK

    with get_connection() as conn:

        # A cursor allows us to execute SQL against PostgreSQL.
        with conn.cursor() as cur:


            # =================================================
            # CHECK WHETHER FILE WAS ALREADY LOADED
            # =================================================

            cur.execute(
                """
                SELECT source_file
                FROM control.file_loads
                WHERE file_hash = %s;
                """,
                (file_hash,),
            )


            # fetchone() returns:
            #
            # tuple -> row was found
            #
            # None -> no row was found
            existing_file = cur.fetchone()


            if existing_file:

                print(
                    f"Already loaded as: {existing_file[0]}"
                )

                print("Skipping file.")

                return


            # =================================================
            # OPEN CSV FILE
            # =================================================

            row_count = 0

            with file_path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:


                # csv.reader() parses the CSV into rows.
                #
                # Each row becomes a Python list.
                reader = csv.reader(csv_file)


                # Retrieve the first row of the CSV.
                #
                # This is the header.
                header = next(reader)


                # =================================================
                # REMOVE NINJATRADER'S TRAILING BLANK COLUMN
                # =================================================
                #
                # Your NinjaTrader export ends lines with:
                #
                # ...,Bars,
                #
                # That final comma creates another empty field:
                #
                # ["Bars", ""]
                #
                # Remove it before validation.

                if header and header[-1] == "":
                    header = header[:-1]


                # =================================================
                # VALIDATE CSV HEADER
                # =================================================

                if header != EXPECTED_COLUMNS:

                    raise ValueError(
                        "CSV columns do not match expected "
                        "NinjaTrader format.\n"
                        f"Expected: {EXPECTED_COLUMNS}\n"
                        f"Received: {header}"
                    )


                # =================================================
                # BULK LOAD RAW DATA USING POSTGRESQL COPY
                # =================================================
                #
                # PostgreSQL COPY is designed for efficiently
                # loading many rows.
                #
                # FROM STDIN means:
                #
                # "The database client (Psycopg) will stream
                # the rows to PostgreSQL."

                with cur.copy(
                    """
                    COPY raw.ninjatrader_trades (
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
                        source_row_number
                    )
                    FROM STDIN
                    """
                ) as copy:


                    # start=2 because:
                    #
                    # CSV row 1 = header
                    # CSV row 2 = first data row

                    for row_number, row in enumerate(
                        reader,
                        start=2,
                    ):


                        # =========================================
                        # REMOVE TRAILING BLANK FIELD
                        # =========================================
                        #
                        # NinjaTrader currently produces:
                        #
                        # 19 actual fields
                        # +
                        # 1 empty field caused by trailing comma

                        if (
                            len(row) == 20
                            and row[-1] == ""
                        ):
                            row = row[:-1]


                        # =========================================
                        # VALIDATE NUMBER OF COLUMNS
                        # =========================================

                        if len(row) != 19:

                            raise ValueError(
                                f"Invalid column count on CSV "
                                f"row {row_number}: "
                                f"expected 19, "
                                f"received {len(row)}"
                            )


                        # =========================================
                        # WRITE ROW TO POSTGRESQL
                        # =========================================
                        #
                        # *row unpacks all 19 CSV values.
                        #
                        # Then we add:
                        #
                        # source_file
                        # source_file_hash
                        # source_row_number

                        copy.write_row(
                            [
                                *row,
                                file_path.name,
                                file_hash,
                                row_number,
                            ]
                        )


                        row_count += 1


            # ====================================================
            # TRANSFORM RAW DATA INTO CLEAN CORE DATA
            # ====================================================

            cur.execute(
                """
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
                    -- ^\\(.*\\)$
                    --
                    -- means:
                    --
                    -- Starts with (
                    -- contains anything
                    -- ends with )

                    CASE

                        WHEN TRIM(profit) ~ '^\\(.*\\)$'

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
                             ~ '^\\(.*\\)$'

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
                """,

                (file_hash,),
            )


            # Number of rows inserted into core.trades.
            core_row_count = cur.rowcount


            # ====================================================
            # RECORD SUCCESSFUL FILE LOAD
            # ====================================================
            #
            # This happens only after:
            #
            # 1. raw COPY succeeds
            # 2. transformation succeeds
            #
            # Because it is part of the same transaction,
            # everything is committed or rolled back together.

            cur.execute(
                """
                INSERT INTO control.file_loads (
                    file_hash,
                    source_file,
                    raw_row_count,
                    core_row_count
                )
                VALUES (%s, %s, %s, %s);
                """,
                (
                    file_hash,
                    file_path.name,
                    row_count,
                    core_row_count,
                ),
            )


    # ============================================================
    # TRANSACTION COMMITS HERE
    # ============================================================

    print()
    print("Load successful.")
    print(f"Raw rows:   {row_count}")
    print(f"Core rows:  {core_row_count}")


# ============================================================
# PROGRAM ENTRY POINT
# ============================================================

def main() -> None:
    """
    Run the loader from the command line.

    Example:

    py load_trades.py "C:\\Users\\Owner\\Dropbox\\trades.csv"
    """

    # sys.argv contains:
    #
    # sys.argv[0] = script name
    # sys.argv[1] = CSV filename
    #
    # Therefore exactly two items should exist.

    if len(sys.argv) != 2:

        print(
            'Usage: py load_trades.py '
            '"C:\\path\\to\\file.csv"'
        )

        sys.exit(1)


    # Convert the command-line path string into a Path object.
    file_path = Path(sys.argv[1])


    # Start the pipeline.
    load_file(file_path)


# ============================================================
# ONLY RUN main() WHEN THIS FILE IS EXECUTED DIRECTLY
# ============================================================

if __name__ == "__main__":
    main()