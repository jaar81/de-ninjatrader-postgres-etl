"""Load one NinjaTrader export into PostgreSQL's raw and core schemas.

Recovered behavior: SHA-256 file identity, UTF-8 BOM handling, the exact
19-column export layout, a single trailing blank field, Psycopg COPY, SQL
cleaning, source metadata, and successful-load tracking in one transaction.

Packaging improvements: an immutable input snapshot, a transaction-scoped
advisory lock for concurrent loads of the same bytes, explicit validation
errors, blank-record skipping, and a layout-only validation command.

Cleaning remains in SQL: install sql/core_transformations.sql before loading.
Trade grouping remains a separate, unfinished analytical step.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Sequence


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

COPY_SQL = """
COPY raw.ninjatrader_trades (
    trade_number, instrument, account, strategy, market_position,
    qty, entry_price, exit_price, entry_time, exit_time,
    entry_name, exit_name, profit, cumulative_net_profit, commission,
    mae, mfe, etd, bars, source_file, source_file_hash, source_row_number
)
FROM STDIN
"""


@dataclass(frozen=True)
class LoadResult:
    """Counts for this attempt; skipped loads insert zero rows."""

    source_file: str
    file_hash: str
    raw_row_count: int
    core_row_count: int
    skipped: bool = False
    previously_loaded_as: str | None = None


def calculate_file_hash(file_path: Path) -> str:
    """Return SHA-256 of the exact file bytes, independent of its filename."""
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as source:
        for chunk in iter(lambda: source.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_header(header: Sequence[str]) -> list[str]:
    """Remove one trailing empty header and validate the recovered layout."""
    columns = list(header)
    if columns and columns[-1] == "":
        columns = columns[:-1]
    if columns != EXPECTED_COLUMNS:
        raise ValueError(
            "CSV columns do not match the expected NinjaTrader format.\n"
            f"Expected: {EXPECTED_COLUMNS}\nReceived: {columns}"
        )
    return columns


def normalize_row(row: Sequence[str], row_number: int) -> list[str]:
    """Validate a record without cleaning or coercing its original values."""
    values = list(row)
    if len(values) == len(EXPECTED_COLUMNS) + 1 and values[-1] == "":
        values = values[:-1]
    if len(values) != len(EXPECTED_COLUMNS):
        raise ValueError(
            f"Invalid column count on CSV record {row_number}: "
            f"expected {len(EXPECTED_COLUMNS)}, received {len(values)}"
        )
    return values


def iter_csv_rows(file_path: Path) -> Iterator[tuple[int, list[str]]]:
    """Yield (source record ordinal, raw values), with header counted as 1.

    A UTF-8 BOM is removed by the decoder. Truly empty records are skipped;
    their ordinals remain counted. A record containing empty fields is still
    validated. Multiline quoted records count once, so the ordinal is not
    necessarily a physical line number.
    """
    with Path(file_path).open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("CSV file is empty; an export header is required.") from exc
        except csv.Error as exc:
            raise ValueError(f"Malformed CSV header: {exc}") from exc
        normalize_header(header)
        try:
            for row_number, row in enumerate(reader, start=2):
                if not row:
                    continue
                yield row_number, normalize_row(row, row_number)
        except csv.Error as exc:
            raise ValueError(
                f"Malformed CSV near physical line {reader.line_num}: {exc}"
            ) from exc


def validate_csv_layout(file_path: Path) -> int:
    """Count records with a valid layout; do not claim SQL values are valid."""
    return sum(1 for _ in iter_csv_rows(file_path))


@contextmanager
def snapshot_csv(file_path: Path) -> Iterator[tuple[Path, str]]:
    """Copy and hash the same bytes so subsequent parsing uses stable input.

    This temporary copy is a packaging improvement. It is deleted on success
    or failure. Leave exports unchanged while the initial copy is being made.
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"CSV file does not exist or is not a file: {file_path}")
    with TemporaryDirectory(prefix="ninjatrader-etl-") as temporary_dir:
        snapshot_path = Path(temporary_dir) / "input.csv"
        digest = hashlib.sha256()
        with file_path.open("rb") as source, snapshot_path.open("wb") as target:
            for chunk in iter(lambda: source.read(8192), b""):
                digest.update(chunk)
                target.write(chunk)
        yield snapshot_path, digest.hexdigest()


def advisory_lock_key(file_hash: str) -> int:
    """Map the first 64 hash bits to PostgreSQL's signed BIGINT lock key.

    The full SHA-256 remains the durable identity. An advisory-key collision
    can only serialize unrelated loads; duplicate checks use the full hash.
    """
    unsigned = int(file_hash[:16], 16)
    return unsigned if unsigned < (1 << 63) else unsigned - (1 << 64)


def get_connection():
    """Connect using PG* settings; no credentials are stored in this project.

    Historical non-secret defaults are preserved. PGPASSWORD or libpq's
    password-file mechanism may provide authentication. Psycopg is imported
    here so layout validation and pure helper tests need only Python.
    """
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Psycopg is required for database loading. Install requirements.txt first."
        ) from exc

    options = {
        "host": os.getenv("PGHOST", "localhost"),
        "port": os.getenv("PGPORT", "5432"),
        "dbname": os.getenv("PGDATABASE", "trading_lab"),
        "user": os.getenv("PGUSER", "postgres"),
    }
    if "PGPASSWORD" in os.environ:
        options["password"] = os.environ["PGPASSWORD"]
    return psycopg.connect(**options)


def load_file(file_path: Path) -> LoadResult:
    """Atomically COPY raw records, transform this hash, and record success.

    Setup SQL must have been installed first. No grouping SQL is executed.
    An exception rolls back raw rows, core rows, and the success record.
    """
    file_path = Path(file_path)
    with snapshot_csv(file_path) as (snapshot_path, file_hash):
        with get_connection() as conn:
            with conn.cursor() as cur:
                # New hardening: simultaneous attempts for the same input wait
                # for the first transaction before checking its success record.
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s);",
                    (advisory_lock_key(file_hash),),
                )
                cur.execute(
                    "SELECT source_file FROM control.file_loads WHERE file_hash = %s;",
                    (file_hash,),
                )
                existing_file = cur.fetchone()
                if existing_file:
                    return LoadResult(
                        file_path.name, file_hash, 0, 0,
                        skipped=True, previously_loaded_as=existing_file[0],
                    )

                row_count = 0
                with cur.copy(COPY_SQL) as copy:
                    for row_number, row in iter_csv_rows(snapshot_path):
                        copy.write_row(
                            [*row, file_path.name, file_hash, row_number]
                        )
                        row_count += 1

                # Recovered raw-to-core cleaning is factored into a reusable
                # database function in sql/core_transformations.sql.
                cur.execute("SELECT core.load_trades(%s);", (file_hash,))
                transformation_result = cur.fetchone()
                if transformation_result is None:
                    raise RuntimeError("core.load_trades did not return an inserted row count.")
                core_row_count = int(transformation_result[0])

                cur.execute(
                    """
                    INSERT INTO control.file_loads (
                        file_hash, source_file, raw_row_count, core_row_count
                    ) VALUES (%s, %s, %s, %s);
                    """,
                    (file_hash, file_path.name, row_count, core_row_count),
                )
        return LoadResult(file_path.name, file_hash, row_count, core_row_count)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="NinjaTrader trade-history CSV export")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Check CSV layout without connecting to PostgreSQL or validating SQL conversions",
    )
    args = parser.parse_args(argv)
    try:
        if args.validate_only:
            count = validate_csv_layout(args.csv_file)
            print(f"CSV layout valid: {count} data row(s). SQL transformations were not executed.")
            return 0
        result = load_file(args.csv_file)
    except Exception as exc:
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1

    print(f"Source file: {result.source_file}")
    print(f"SHA-256: {result.file_hash}")
    if result.skipped:
        print(f"Already loaded as: {result.previously_loaded_as}. Skipping file.")
    else:
        print(f"Load successful. Raw rows: {result.raw_row_count}; core rows: {result.core_row_count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
