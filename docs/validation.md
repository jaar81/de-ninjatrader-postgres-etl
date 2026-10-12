# Validation

Local validation completed October 12, 2026 using Python **3.12.14**, Psycopg **3.3.6**, and PostgreSQL **18.6** on Windows. All database work used a newly initialized, isolated test instance and synthetic records. The user's existing PostgreSQL databases were not used.

## Results

| Check | Result |
| --- | --- |
| Fresh schema/table/function setup | Passed |
| Automated suite | **29 tests passed**: 14 pure Python tests and 15 PostgreSQL tests |
| Sample layout check | 24 valid CSV records |
| Sample loader through the real CLI | 24 raw rows, 24 core rows, 1 success record |
| Second identical sample load | Skipped; no extra data or success record |
| Analysis queries | Executed; raw/core reconciliation differences both zero |
| Optional grouping SQL | Created and queried successfully; all 24 rows labeled `experimental_unverified` |
| Dependency consistency | `pip check` passed |

Executing the candidate view proves SQL compatibility only. It does not prove correct logical trade boundaries or resolve the historical grouping failure. The GitHub Actions workflow is included but was not run on GitHub during packaging. Other Python/PostgreSQL versions and operating systems have not been tested for this package.

## Covered behaviors

Pure tests exercise known SHA-256 output, filename-independent identity, changed-byte identity, exact/rejected headers, raw-value preservation, invalid row widths, BOM and trailing blank fields, quoted thousands separators, skipped empty records, multiline record ordinals, empty/header-only files, malformed CSV, layout-only validation, stable snapshot bytes, and sample properties.

PostgreSQL tests exercise real COPY and SQL transformations, raw/core lineage, renamed-file duplicate skipping, changed-content loading, atomic rollback on malformed rows and invalid SQL values, repeat core transformation, midnight/noon and HH24 parsing, accounting losses, malformed money/date rejection, two-decimal rounding, numeric overflow rollback, committed visibility from an independent connection, rollback after connection closure, and two simultaneous identical-file attempts producing exactly one load and one skip.

## Run pure tests

From the repository root:

```powershell
py -3.12 -m unittest discover -s tests -v
```

With no `TEST_DATABASE_DSN`, the 14 pure tests run and the 15 database tests are explicitly skipped. Pure tests do not require Psycopg.

## Run the full suite

Install `requirements.txt` in the virtual environment as described in the README. Configure your local PostgreSQL authentication, then create a **disposable** test database. Use your own authorized development role in place of `postgres` if needed.

```powershell
$env:PGHOST = 'localhost'
$env:PGPORT = '5432'
$env:PGUSER = 'postgres'
$env:PGDATABASE = 'trading_etl_test'
createdb trading_etl_test

psql -v ON_ERROR_STOP=1 -f sql/create_schemas.sql
psql -v ON_ERROR_STOP=1 -f sql/create_tables.sql
psql -v ON_ERROR_STOP=1 -f sql/core_transformations.sql
psql -v ON_ERROR_STOP=1 -f sql/trade_grouping.sql

$env:TEST_DATABASE_DSN = "host=$env:PGHOST port=$env:PGPORT dbname=$env:PGDATABASE user=$env:PGUSER"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The connection uses your PostgreSQL password file or `PGPASSWORD`; the example DSN contains no password. `create_tables.sql` is intended for initial setup and will fail if tables already exist. For another test run against that same initialized test database, run only the test command.

Database tests in `test_transformations.py` wrap their data in an outer rollback and run loader operations through savepoints. The separate `test_integration.py` tests use independent connections and commit synthetic fixtures. Those fixtures have unique account tokens and are cleaned up only by their exact file hashes; no table-wide deletion is performed. A forced interruption can leave synthetic fixtures behind, which is another reason to use a disposable database.

## Remaining validation

- Compare the reconstructed schema with the original deployment before planning a migration.
- Validate real export variants, source timezone, price precision, and commission semantics.
- Recover a manually labeled example of the reported grouping problem and verify actual group membership, scale ownership, and boundary behavior.
- Measure larger-file performance and production operational behavior separately; no benchmark is claimed.
