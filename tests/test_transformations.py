"""CSV regression tests and optional tests of the actual PostgreSQL pipeline.

Run from the repository root: python -m unittest discover -s tests -v
Pure CSV tests need only Python. Database tests are skipped unless
TEST_DATABASE_DSN points to a disposable database with the three setup SQL
files installed. They roll back their data; no trade-grouping correctness is
asserted because the business grouping rules remain unfinished.
"""

from __future__ import annotations

import csv
import io
import os
import unittest
import uuid
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import load_trades as etl


ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = os.getenv("TEST_DATABASE_DSN")


def representative_row() -> list[str]:
    """Invented values exercising the export's formatting, not real history."""
    return [
        "1", " ES 12-24 ", "SIM_TEST", " SyntheticExample ", "Buy", "2",
        "$5,030.25", "$5,005.25", "09/03/2024 14:00:00",
        "9/3/2024 2:15:00 PM", " A ", "SyntheticExit", "($1,250.00)",
        "($2,500.50)", "$2.50", "$125.00", "$250.00", "$125.00", "15",
    ]


def write_csv(path: Path, rows: list[list[str]], *, trailing_blank=False, bom=False):
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(etl.EXPECTED_COLUMNS + ([""] if trailing_blank else []))
        for row in rows:
            writer.writerow(row + ([""] if trailing_blank else []))


class CsvTransformationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_dir = TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.path = Path(self.temporary_dir.name) / "synthetic.csv"

    def test_sha256_known_vector(self):
        self.path.write_bytes(b"abc")
        self.assertEqual(
            etl.calculate_file_hash(self.path),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )

    def test_file_identity_depends_on_exact_bytes_not_name(self):
        self.path.write_bytes(b"same content")
        renamed = self.path.with_name("renamed.csv")
        renamed.write_bytes(self.path.read_bytes())
        self.assertEqual(etl.calculate_file_hash(self.path), etl.calculate_file_hash(renamed))
        renamed.write_bytes(b"same content\n")
        self.assertNotEqual(etl.calculate_file_hash(self.path), etl.calculate_file_hash(renamed))

    def test_exact_header_and_one_trailing_blank_are_accepted(self):
        expected = list(etl.EXPECTED_COLUMNS)
        self.assertEqual(etl.normalize_header(expected), expected)
        self.assertEqual(etl.normalize_header(expected + [""]), expected)

    def test_reordered_missing_and_extra_headers_are_rejected(self):
        cases = [
            etl.EXPECTED_COLUMNS[1:] + etl.EXPECTED_COLUMNS[:1],
            etl.EXPECTED_COLUMNS[:-1],
            etl.EXPECTED_COLUMNS + ["Unexpected"],
            etl.EXPECTED_COLUMNS + ["", ""],
        ]
        for header in cases:
            with self.subTest(header=header), self.assertRaises(ValueError):
                etl.normalize_header(header)

    def test_raw_values_are_preserved_for_sql_cleaning(self):
        row = representative_row()
        self.assertEqual(etl.normalize_row(row, 2), row)
        self.assertEqual(etl.normalize_row(row + [""], 2), row)
        self.assertEqual(row[1], " ES 12-24 ")
        self.assertEqual(row[12], "($1,250.00)")

    def test_wrong_row_width_includes_source_record_in_error(self):
        for row in [representative_row()[:-1], representative_row() + ["extra"], representative_row() + ["", ""]]:
            with self.subTest(width=len(row)), self.assertRaisesRegex(ValueError, "record 7"):
                etl.normalize_row(row, 7)

    def test_bom_trailing_fields_and_quoted_thousands_are_read(self):
        row = representative_row()
        write_csv(self.path, [row], trailing_blank=True, bom=True)
        self.assertTrue(self.path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(list(etl.iter_csv_rows(self.path)), [(2, row)])

    def test_blank_records_are_skipped_without_renumbering(self):
        row = representative_row()
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(etl.EXPECTED_COLUMNS)
            writer.writerow(row)
            writer.writerow([])
            writer.writerow(row)
        self.assertEqual([number for number, _ in etl.iter_csv_rows(self.path)], [2, 4])

    def test_multiline_csv_field_remains_one_source_record(self):
        row = representative_row()
        row[3] = "Synthetic\nExample"
        write_csv(self.path, [row, representative_row()])
        records = list(etl.iter_csv_rows(self.path))
        self.assertEqual([number for number, _ in records], [2, 3])
        self.assertEqual(records[0][1][3], "Synthetic\nExample")

    def test_empty_file_rejected_but_header_only_has_zero_records(self):
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            list(etl.iter_csv_rows(self.path))
        write_csv(self.path, [])
        self.assertEqual(etl.validate_csv_layout(self.path), 0)

    def test_unterminated_quoted_field_is_rejected(self):
        write_csv(self.path, [])
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('"unterminated field')
        with self.assertRaisesRegex(ValueError, "Malformed CSV"):
            list(etl.iter_csv_rows(self.path))

    def test_validate_only_never_connects_or_claims_sql_validation(self):
        row = representative_row()
        row[5] = "not an integer"
        write_csv(self.path, [row])
        output = io.StringIO()
        with patch.object(etl, "get_connection", side_effect=AssertionError("Unexpected database access")), redirect_stdout(output):
            self.assertEqual(etl.main([str(self.path), "--validate-only"]), 0)
        self.assertIn("SQL transformations were not executed", output.getvalue())

    def test_snapshot_hash_and_parsing_use_the_same_stable_bytes(self):
        original = representative_row()
        write_csv(self.path, [original], bom=True)
        expected_hash = etl.calculate_file_hash(self.path)
        with etl.snapshot_csv(self.path) as (snapshot, file_hash):
            self.path.write_text("source changed after snapshot", encoding="utf-8")
            self.assertEqual(file_hash, expected_hash)
            self.assertEqual(etl.calculate_file_hash(snapshot), expected_hash)
            self.assertEqual(list(etl.iter_csv_rows(snapshot)), [(2, original)])
        self.assertFalse(snapshot.exists())

    def test_distributed_sample_is_synthetic_and_has_required_edge_formats(self):
        sample = ROOT / "sample_data" / "sample_trades.csv"
        records = list(etl.iter_csv_rows(sample))
        self.assertEqual(len(records), 24)
        self.assertEqual([number for number, _ in records], list(range(2, 26)))
        rows = [row for _, row in records]
        self.assertEqual({row[2] for row in rows}, {"SIM_PORTFOLIO"})
        self.assertEqual({row[4] for row in rows}, {"Buy", "Sell"})
        self.assertTrue(any(row[12].startswith("(") for row in rows))
        self.assertTrue(any(row[13].startswith("(") for row in rows))
        self.assertTrue(any(row[8].endswith("AM") for row in rows))
        self.assertTrue(any("14:00:00" in row[8] for row in rows))
        self.assertEqual({row[10] for row in rows}, {"A", "B", "C", "D", "E", "Scale C", "Scale D", "Scale E"})


@unittest.skipUnless(TEST_DSN, "Set TEST_DATABASE_DSN to run actual PostgreSQL transformations")
class PostgreSQLTransformationsTests(unittest.TestCase):
    """Real COPY/SQL tests; each test's writes stay in an outer rollback.

    A nested transaction replaces only the connection context used by the
    loader. COPY, constraints, SQL conversion, and duplicate checks all run
    against PostgreSQL. This does not exercise concurrent connections.
    """

    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.conn = psycopg.connect(TEST_DSN)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.conn.execute("SELECT 1")  # Begin the outer transaction before savepoints.
        self.temporary_dir = TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.path = Path(self.temporary_dir.name) / "synthetic_test.csv"
        self.row = representative_row()
        self.row[2] = "SYNTHETIC_TEST_" + uuid.uuid4().hex

        @contextmanager
        def connection_context():
            with self.conn.transaction():
                yield self.conn

        connection_patch = patch.object(etl, "get_connection", side_effect=connection_context)
        connection_patch.start()
        self.addCleanup(connection_patch.stop)

    def load(self, rows=None):
        write_csv(self.path, rows if rows is not None else [self.row], trailing_blank=True, bom=True)
        return etl.load_file(self.path)

    def counts(self, file_hash):
        return tuple(
            self.conn.execute(query, (file_hash,)).fetchone()[0]
            for query in (
                "SELECT count(*) FROM raw.ninjatrader_trades WHERE source_file_hash = %s",
                "SELECT count(*) FROM core.trades WHERE source_file_hash = %s",
                "SELECT count(*) FROM control.file_loads WHERE file_hash = %s",
            )
        )

    def test_copy_preserves_raw_and_sql_cleans_values_with_metadata(self):
        result = self.load()
        self.assertEqual((result.raw_row_count, result.core_row_count, result.skipped), (1, 1, False))
        raw = self.conn.execute(
            "SELECT instrument, profit, entry_time, source_file, source_row_number, loaded_at "
            "FROM raw.ninjatrader_trades WHERE source_file_hash = %s", (result.file_hash,),
        ).fetchone()
        self.assertEqual(raw[:5], (" ES 12-24 ", "($1,250.00)", "09/03/2024 14:00:00", self.path.name, 2))
        self.assertIsNotNone(raw[5])
        core = self.conn.execute(
            "SELECT trade_number, instrument, strategy, qty, entry_price, exit_price, "
            "entry_time, exit_time, entry_name, profit, cumulative_net_profit, commission, "
            "source_file, source_row_number, loaded_at FROM core.trades WHERE source_file_hash = %s",
            (result.file_hash,),
        ).fetchone()
        self.assertEqual(core[:14], (
            1, "ES 12-24", "SyntheticExample", 2, Decimal("5030.25"), Decimal("5005.25"),
            datetime(2024, 9, 3, 14, 0), datetime(2024, 9, 3, 14, 15), "A",
            Decimal("-1250.00"), Decimal("-2500.50"), Decimal("2.50"), self.path.name, 2,
        ))
        self.assertEqual(core[14], raw[5])
        self.assertEqual(self.counts(result.file_hash), (1, 1, 1))

    def test_same_bytes_under_another_filename_are_skipped(self):
        first = self.load()
        renamed = self.path.with_name("renamed_export.csv")
        renamed.write_bytes(self.path.read_bytes())
        duplicate = etl.load_file(renamed)
        self.assertTrue(duplicate.skipped)
        self.assertEqual(duplicate.file_hash, first.file_hash)
        self.assertEqual(duplicate.previously_loaded_as, self.path.name)
        self.assertEqual((duplicate.raw_row_count, duplicate.core_row_count), (0, 0))
        self.assertEqual(self.counts(first.file_hash), (1, 1, 1))

    def test_same_filename_with_changed_bytes_is_a_new_load(self):
        first = self.load()
        changed = list(self.row)
        changed[0] = "2"
        second = self.load([changed])
        self.assertFalse(second.skipped)
        self.assertNotEqual(first.file_hash, second.file_hash)
        self.assertEqual(self.counts(first.file_hash), (1, 1, 1))
        self.assertEqual(self.counts(second.file_hash), (1, 1, 1))

    def test_failed_sql_conversion_rolls_back_raw_and_control_records(self):
        invalid = list(self.row)
        invalid[5] = "invalid quantity"
        write_csv(self.path, [self.row, invalid])
        file_hash = etl.calculate_file_hash(self.path)
        with self.assertRaises(self.psycopg.Error):
            etl.load_file(self.path)
        self.assertEqual(self.counts(file_hash), (0, 0, 0))

    def test_failed_csv_record_after_a_valid_record_rolls_back_copy(self):
        write_csv(self.path, [self.row, self.row[:-1]])
        file_hash = etl.calculate_file_hash(self.path)
        with self.assertRaises(ValueError):
            etl.load_file(self.path)
        self.assertEqual(self.counts(file_hash), (0, 0, 0))

    def test_repeat_core_transformation_is_idempotent_for_file_and_row(self):
        result = self.load()
        inserted = self.conn.execute("SELECT core.load_trades(%s)", (result.file_hash,)).fetchone()[0]
        self.assertEqual(inserted, 0)
        self.assertEqual(self.counts(result.file_hash), (1, 1, 1))

    def test_midnight_and_noon_timestamp_formats(self):
        cases = [
            ("9/3/2024 12:00:00 AM", datetime(2024, 9, 3, 0, 0)),
            ("9/3/2024 12:00:00 PM", datetime(2024, 9, 3, 12, 0)),
            ("09/03/2024 23:59:59", datetime(2024, 9, 3, 23, 59, 59)),
            ("", None),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                actual = self.conn.execute("SELECT core.parse_trade_timestamp(%s)", (source,)).fetchone()[0]
                self.assertEqual(actual, expected)

    def test_accounting_losses_signed_values_and_blank_money(self):
        cases = [
            ("($1,250.50)", Decimal("-1250.50")),
            ("(125.50)", Decimal("-125.50")),
            ("-$125.50", Decimal("-125.50")),
            ("$-10", Decimal("-10")),
            (".50", Decimal("0.50")),
            ("10.", Decimal("10")),
            ("$1,250.50", Decimal("1250.50")),
            ("", None),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                actual = self.conn.execute("SELECT core.parse_money(%s, true)", (source,)).fetchone()[0]
                self.assertEqual(actual, expected)

    def test_malformed_money_and_unsupported_accounting_fields_are_rejected(self):
        for source in ["12,34", "($-10)", "NaN", "Infinity", "1e3", "$$10", "(10", "EUR10"]:
            with self.subTest(source=source), self.assertRaises(self.psycopg.Error):
                with self.conn.transaction():
                    self.conn.execute("SELECT core.parse_money(%s, true)", (source,))
        with self.assertRaises(self.psycopg.Error):
            with self.conn.transaction():
                self.conn.execute("SELECT core.parse_money(%s, false)", ("($10)",))

    def test_invalid_dates_times_and_formats_are_rejected(self):
        cases = [
            "02/30/2024 14:00:00", "13/01/2024 14:00:00",
            "02/29/2023 14:00:00", "09/03/2024 24:00:00",
            "09/03/2024 14:00:00 PM", "09/03/2024 00:00:00 AM",
            "09/03/2024 14:60:00", "09/03/2024 14:00:60",
            "2024-09-03T14:00:00",
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(self.psycopg.Error):
                with self.conn.transaction():
                    self.conn.execute("SELECT core.parse_trade_timestamp(%s)", (source,))

    def test_core_numeric_precision_rounds_at_two_decimals(self):
        self.row[6] = "$123.4567"
        self.row[12] = "($1,234.565)"
        self.row[13] = "$9999999999999999.99"
        result = self.load()
        values = self.conn.execute(
            "SELECT entry_price, profit, cumulative_net_profit FROM core.trades "
            "WHERE source_file_hash = %s", (result.file_hash,),
        ).fetchone()
        self.assertEqual(values, (Decimal("123.46"), Decimal("-1234.57"), Decimal("9999999999999999.99")))

    def test_numeric_overflow_rolls_back_load(self):
        self.row[6] = "$10000000000000000.00"
        write_csv(self.path, [self.row])
        file_hash = etl.calculate_file_hash(self.path)
        with self.assertRaises(self.psycopg.Error):
            etl.load_file(self.path)
        self.assertEqual(self.counts(file_hash), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
