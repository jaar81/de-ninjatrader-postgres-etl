"""Optional commit/concurrency tests for a disposable PostgreSQL database.

Set TEST_DATABASE_DSN after installing the setup SQL, then run:
    python -m unittest discover -s tests -v

These tests open independent real connections and commit synthetic rows.
Each fixture contains a unique account token, and cleanup deletes only that
fixture's exact SHA-256 hashes. No table-wide deletion is performed. Grouping
business correctness is intentionally outside these ETL integration tests.
"""

from __future__ import annotations

import csv
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from src import load_trades as etl


TEST_DSN = os.getenv("TEST_DATABASE_DSN")


@unittest.skipUnless(TEST_DSN, "Set TEST_DATABASE_DSN to run PostgreSQL connection integration tests")
class DatabaseConnectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.hashes = set()
        self.temporary_dir = TemporaryDirectory()
        self.addCleanup(self.temporary_dir.cleanup)
        self.path = Path(self.temporary_dir.name) / "synthetic_integration.csv"
        self.row = [
            "1", "ES 12-24", "SYNTHETIC_INTEGRATION_" + uuid.uuid4().hex,
            "SyntheticExample", "Buy", "1", "$5,000.00", "$5,010.00",
            "09/03/2024 14:00:00", "09/03/2024 14:10:00", "A", "SyntheticExit",
            "$500.00", "$500.00", "$2.50", "$125.00", "$625.00", "$125.00", "10",
        ]
        self.addCleanup(self.remove_fixture_rows)
        connection_patch = patch.object(
            etl, "get_connection", side_effect=lambda: self.psycopg.connect(TEST_DSN),
        )
        connection_patch.start()
        self.addCleanup(connection_patch.stop)

    def write_fixture(self, rows=None):
        with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(etl.EXPECTED_COLUMNS + [""])
            for row in rows if rows is not None else [self.row]:
                writer.writerow(row + [""])
        file_hash = etl.calculate_file_hash(self.path)
        self.hashes.add(file_hash)
        return file_hash

    def remove_fixture_rows(self):
        if not self.hashes:
            return
        with self.psycopg.connect(TEST_DSN) as conn:
            for file_hash in self.hashes:
                conn.execute("DELETE FROM core.trades WHERE source_file_hash = %s", (file_hash,))
                conn.execute("DELETE FROM raw.ninjatrader_trades WHERE source_file_hash = %s", (file_hash,))
                conn.execute("DELETE FROM control.file_loads WHERE file_hash = %s", (file_hash,))

    def observer_counts(self, file_hash):
        # This independent connection cannot see another connection's uncommitted rows.
        with self.psycopg.connect(TEST_DSN) as observer:
            return tuple(
                observer.execute(query, (file_hash,)).fetchone()[0]
                for query in (
                    "SELECT count(*) FROM raw.ninjatrader_trades WHERE source_file_hash = %s",
                    "SELECT count(*) FROM core.trades WHERE source_file_hash = %s",
                    "SELECT count(*) FROM control.file_loads WHERE file_hash = %s",
                )
            )

    def test_independent_observer_sees_committed_success(self):
        file_hash = self.write_fixture()
        result = etl.load_file(self.path)
        self.assertFalse(result.skipped)
        self.assertEqual(self.observer_counts(file_hash), (1, 1, 1))
        with self.psycopg.connect(TEST_DSN) as observer:
            counts = observer.execute(
                "SELECT raw_row_count, core_row_count FROM control.file_loads WHERE file_hash = %s",
                (file_hash,),
            ).fetchone()
        self.assertEqual(counts, (1, 1))

    def test_sql_failure_leaves_no_rows_after_connection_exits(self):
        invalid_row = list(self.row)
        invalid_row[5] = "not a quantity"
        file_hash = self.write_fixture([self.row, invalid_row])
        with self.assertRaises(self.psycopg.Error):
            etl.load_file(self.path)
        self.assertEqual(self.observer_counts(file_hash), (0, 0, 0))

    def test_concurrent_identical_files_load_once(self):
        file_hash = self.write_fixture()
        start = Barrier(2)

        def attempt_load():
            start.wait(timeout=10)
            return etl.load_file(self.path)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(attempt_load) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(sorted(result.skipped for result in results), [False, True])
        self.assertEqual(sum(result.raw_row_count for result in results), 1)
        self.assertEqual(sum(result.core_row_count for result in results), 1)
        self.assertTrue(all(result.file_hash == file_hash for result in results))
        self.assertEqual(self.observer_counts(file_hash), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
