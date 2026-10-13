"""Regression checks for the original, unchanged loader.

Install requirements.txt, then run: python -m unittest discover -s tests -v
Database tests require TEST_DATABASE_DSN for an initialized disposable database.
They use real COPY and the loader's inline SQL inside rollback-only tests.
These tests do not establish that historical trade-grouping issues are solved.
"""

import csv
import importlib.util
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

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("original_loader", ROOT / "src" / "load_trades.py")
etl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(etl)
TEST_DSN = os.getenv("TEST_DATABASE_DSN")


class FileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.csv"

    def test_sha256_known_bytes(self):
        self.path.write_bytes(b"abc")
        self.assertEqual(etl.calculate_file_hash(self.path),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_hash_uses_content_not_filename(self):
        self.path.write_bytes(b"synthetic data")
        renamed = self.path.with_name("renamed.csv")
        renamed.write_bytes(self.path.read_bytes())
        self.assertEqual(etl.calculate_file_hash(self.path), etl.calculate_file_hash(renamed))
        renamed.write_bytes(b"changed synthetic data")
        self.assertNotEqual(etl.calculate_file_hash(self.path), etl.calculate_file_hash(renamed))

    def test_distributed_sample_matches_the_original_export_layout(self):
        sample = ROOT / "sample_data" / "sample_trades.csv"
        self.assertTrue(sample.read_bytes().startswith(b"\xef\xbb\xbf"))
        with sample.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], etl.EXPECTED_COLUMNS + [""])
        self.assertEqual(len(rows[1:]), 24)
        self.assertTrue(all(len(row) == 20 and row[-1] == "" for row in rows[1:]))


@unittest.skipUnless(TEST_DSN, "Set TEST_DATABASE_DSN to test PostgreSQL transformations")
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.conn = psycopg.connect(TEST_DSN)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.conn.execute("SELECT 1")  # Outer transaction contains all test writes.
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.csv"
        self.row = [
            "1", " ES 12-24 ", "SYNTHETIC_TEST_" + uuid.uuid4().hex,
            " SyntheticExample ", "Buy", "1", "$5,030.25", "$5,005.25",
            "09/03/2024 14:00:00", "9/3/2024 2:15:00 PM", " A ", "SyntheticExit",
            "($1,250.00)", "($2,500.50)", "$2.50", "$125.00", "$250.00", "$125.00", "15",
        ]

        @contextmanager
        def connection_context():
            with self.conn.transaction():  # Real database savepoint, not mocked SQL.
                yield self.conn

        connection_patch = patch.object(etl, "get_connection", side_effect=connection_context)
        connection_patch.start()
        self.addCleanup(connection_patch.stop)

    def write_csv(self, rows=None, header=None):
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow((etl.EXPECTED_COLUMNS if header is None else header) + [""])
            for row in [self.row] if rows is None else rows:
                writer.writerow(row + [""])
        return etl.calculate_file_hash(self.path)

    def load(self, path=None):
        output = io.StringIO()
        with redirect_stdout(output):
            etl.load_file(path or self.path)
        return output.getvalue()

    def counts(self, file_hash):
        return tuple(self.conn.execute(query, (file_hash,)).fetchone()[0] for query in (
            "SELECT count(*) FROM raw.ninjatrader_trades WHERE source_file_hash = %s",
            "SELECT count(*) FROM core.trades WHERE source_file_hash = %s",
            "SELECT count(*) FROM control.file_loads WHERE file_hash = %s",
        ))

    def test_bom_blank_column_raw_values_cleaning_and_metadata(self):
        file_hash = self.write_csv()
        self.load()
        raw = self.conn.execute(
            "SELECT instrument, profit, entry_time, source_file, source_row_number, loaded_at "
            "FROM raw.ninjatrader_trades WHERE source_file_hash = %s", (file_hash,),
        ).fetchone()
        self.assertEqual(raw[:5], (" ES 12-24 ", "($1,250.00)", "09/03/2024 14:00:00", self.path.name, 2))
        self.assertIsNotNone(raw[5])
        core = self.conn.execute(
            "SELECT instrument, strategy, qty, entry_price, entry_time, exit_time, entry_name, "
            "profit, cumulative_net_profit, commission, source_file, source_row_number, loaded_at "
            "FROM core.trades WHERE source_file_hash = %s", (file_hash,),
        ).fetchone()
        self.assertEqual(core[:12], (
            "ES 12-24", "SyntheticExample", 1, Decimal("5030.25"),
            datetime(2024, 9, 3, 14), datetime(2024, 9, 3, 14, 15), "A",
            Decimal("-1250.00"), Decimal("-2500.50"), Decimal("2.50"), self.path.name, 2,
        ))
        self.assertEqual(core[12], raw[5])
        self.assertEqual(self.counts(file_hash), (1, 1, 1))

    def test_midnight_noon_and_afternoon_timestamp_parsing(self):
        rows = []
        for number, (entry, exit_) in enumerate([
            ("9/3/2024 12:00:00 AM", "9/3/2024 12:00:00 PM"),
            ("09/03/2024 14:35:00", "09/03/2024 23:59:59"),
        ], start=1):
            row = list(self.row)
            row[0], row[8], row[9] = str(number), entry, exit_
            rows.append(row)
        file_hash = self.write_csv(rows)
        self.load()
        values = self.conn.execute(
            "SELECT entry_time, exit_time FROM core.trades WHERE source_file_hash = %s "
            "ORDER BY source_row_number", (file_hash,),
        ).fetchall()
        self.assertEqual(values, [
            (datetime(2024, 9, 3), datetime(2024, 9, 3, 12)),
            (datetime(2024, 9, 3, 14, 35), datetime(2024, 9, 3, 23, 59, 59)),
        ])

    def test_identical_bytes_under_new_filename_are_skipped(self):
        file_hash = self.write_csv()
        self.load()
        renamed = self.path.with_name("renamed.csv")
        renamed.write_bytes(self.path.read_bytes())
        self.assertIn("Skipping file.", self.load(renamed))
        self.assertEqual(self.counts(file_hash), (1, 1, 1))

    def test_bad_quantity_rolls_back_all_rows(self):
        invalid = list(self.row)
        invalid[5] = "invalid quantity"
        file_hash = self.write_csv([self.row, invalid])
        with self.assertRaises(self.psycopg.Error):
            self.load()
        self.assertEqual(self.counts(file_hash), (0, 0, 0))

    def test_wrong_csv_width_rolls_back_prior_valid_record(self):
        file_hash = self.write_csv([self.row, self.row[:-2]])
        with self.assertRaisesRegex(ValueError, "Invalid column count"):
            self.load()
        self.assertEqual(self.counts(file_hash), (0, 0, 0))

    def test_supplied_grouping_overlap_and_equal_exit_boundary(self):
        # Characterize the supplied view on invented data only. This is not
        # proof that the historical grouping failure has been resolved.
        # Its partition is direction only, so isolate with a synthetic label.
        direction = "SYNTHETIC_DIRECTION_" + uuid.uuid4().hex
        rows = []
        for number, (entry, exit_) in enumerate([
            ("10:00:00", "10:20:00"), ("10:00:00", "10:05:00"),
            ("10:06:00", "10:08:00"), ("10:19:00", "10:25:00"),
            ("10:25:00", "10:30:00"), ("10:40:00", "10:50:00"),
        ], start=1):
            row = list(self.row)
            row[0], row[4] = str(number), direction
            row[8], row[9] = "09/03/2024 " + entry, "09/03/2024 " + exit_
            rows.append(row)
        file_hash = self.write_csv(rows)
        self.load()
        grouped = self.conn.execute(
            "SELECT trade_number, direction_group_number, group_start_time, trade_group_key "
            "FROM analytics.grouped_trades WHERE source_file_hash = %s ORDER BY trade_number",
            (file_hash,),
        ).fetchall()
        self.assertEqual([row[0] for row in grouped], [1, 2, 3, 4, 5, 6])
        self.assertEqual([row[1] for row in grouped], [1, 1, 1, 1, 2, 3])
        self.assertEqual([row[2] for row in grouped], [datetime(2024, 9, 3, 10)] * 4 +
                         [datetime(2024, 9, 3, 10, 25), datetime(2024, 9, 3, 10, 40)])
        self.assertEqual(len({row[3] for row in grouped}), 3)

    def test_wrong_header_rejected_without_database_rows(self):
        file_hash = self.write_csv(header=etl.EXPECTED_COLUMNS[1:] + etl.EXPECTED_COLUMNS[:1])
        with self.assertRaisesRegex(ValueError, "CSV columns do not match"):
            self.load()
        self.assertEqual(self.counts(file_hash), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
