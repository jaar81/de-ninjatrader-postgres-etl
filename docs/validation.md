# Validation

Checked on October 13, 2026 using Python 3.12.14, Psycopg 3.3.6, and PostgreSQL 18.6 on Windows. Testing used an isolated database and synthetic records.

| Check | Result |
| --- | --- |
| Original Python file comparison | Byte-for-byte match with the supplied `load_trades.py` |
| Grouping SQL comparison | Matches the supplied SQL |
| Fresh schema/table setup | Passed |
| Automated tests | 10 passed: 3 file tests and 7 PostgreSQL tests |
| Original loader, first sample run | 24 raw rows, 24 core rows, one successful load |
| Original loader, repeated sample run | Duplicate skipped |
| Supplied grouping view on the sample | 24 rows in three illustrative groups |
| Analysis queries | Executed successfully |

The database tests cover raw values and metadata, BOM/trailing-column handling, accounting losses, HH12/HH24 timestamps, duplicate skipping, rollback after invalid quantities or malformed CSV input, and selected overlap/equality-boundary behavior of the supplied grouping query.

The grouping checks use invented records. They do not establish that the previously reported seven-record grouping issue is fixed. No changes were made to the user's existing database or original Python file.

## Run the tests

Install `requirements.txt`, then run from the repository root:

```powershell
py -m unittest discover -s tests -v
```

Without `TEST_DATABASE_DSN`, the three file tests run and seven database tests skip. Psycopg must be installed because the original script imports it when loaded.

For the full suite, use a new disposable database with the supplied schemas, tables, and grouping view installed. Keep your existing local `PGHOST`, `PGPORT`, `PGUSER`, and `PGPASSWORD` connection settings:

```powershell
createdb trading_etl_test
$env:PGDATABASE = 'trading_etl_test'
psql -v ON_ERROR_STOP=1 -f sql/create_schemas.sql
psql -v ON_ERROR_STOP=1 -f sql/create_tables.sql
psql -v ON_ERROR_STOP=1 -f sql/trade_grouping.sql
$env:TEST_DATABASE_DSN = "host=$env:PGHOST port=$env:PGPORT dbname=$env:PGDATABASE user=$env:PGUSER"
py -m unittest discover -s tests -v
```

The tests use real COPY and the original inline SQL. They replace only the connection context with a savepoint inside an outer transaction, which is rolled back after each test. They do not test concurrent loading. The separate sample command-line runs verify a normal committed load and subsequent duplicate skip.

For another run against the initialized test database, run just the test command. Restore `PGDATABASE` to your usual database afterward. Table creation is initial setup only, not a migration.
