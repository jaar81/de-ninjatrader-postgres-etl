# NinjaTrader Trading ETL Pipeline

A Python and PostgreSQL project that loads NinjaTrader trade-history CSV exports, cleans the data, prevents duplicate file loads, and prepares execution records for trading analysis.

This version uses the **original working `load_trades.py`, unchanged**, and the supplied SQL for **`analytics.grouped_trades`**. All raw-to-core transformation SQL stays inside the Python script.

## How it works

```text
NinjaTrader CSV
     |
     v
load_trades.py -- SHA-256 check against control.file_loads
     |
     v
raw.ninjatrader_trades -- source values and metadata
     |
     v
core.trades -- cleaned numbers and timestamps
     |
     v
analytics.grouped_trades -- current grouping query
```

The loader writes raw rows, core rows, and the successful-file record in one transaction. If loading or conversion fails, the transaction rolls back.

The project preserves:

- SHA-256 duplicate-file checks in `control.file_loads`.
- UTF-8 BOM handling and removal of the known trailing blank CSV column.
- PostgreSQL COPY into `raw.ninjatrader_trades`.
- Currency cleanup and accounting-style negatives for Profit and Cum. net profit.
- Both AM/PM and `HH24` timestamp parsing.
- Source filename, file hash, row number, and load timestamp.

## Files

```text
trading-etl/
├── README.md
├── requirements.txt
├── .gitignore
├── src/load_trades.py
├── sql/
│   ├── create_schemas.sql
│   ├── create_tables.sql
│   ├── core_transformations.sql  # Reference copy of the SQL inside Python
│   ├── trade_grouping.sql        # Your supplied analytics.grouped_trades view
│   └── analysis_queries.sql
├── sample_data/
│   ├── sample_trades.csv
│   └── README.md
├── docs/
│   ├── architecture.md
│   ├── project_notes.md
│   └── validation.md
└── tests/test_transformations.py
```

## Setup

You need Python, PostgreSQL, and the `psql` command-line tool. Open PowerShell in this repository's root folder.

Install the Python dependency:

```powershell
py -m pip install -r requirements.txt
```

A virtual environment is optional. These instructions use the same straightforward `py` command as the original project.

Set the connection values for your local database. The original script requires `PGPASSWORD`:

```powershell
$env:PGHOST = 'localhost'
$env:PGPORT = '5432'
$env:PGDATABASE = 'trading_lab'
$env:PGUSER = 'postgres'
$env:PGPASSWORD = 'your-local-postgresql-password'
```

Enter your actual password locally; do not put it in a committed file. The script already reads these environment variables.

**If your existing database already has the project's tables, keep using it and skip table creation.** The included table definitions are a compatible reconstruction for a fresh database, not a migration for an existing one.

For a new demo database only:

```powershell
createdb trading_lab_demo
$env:PGDATABASE = 'trading_lab_demo'
psql -v ON_ERROR_STOP=1 -f sql/create_schemas.sql
psql -v ON_ERROR_STOP=1 -f sql/create_tables.sql
```

## Load a CSV

```powershell
py src/load_trades.py sample_data/sample_trades.csv
```

Or supply the path to your own export:

```powershell
py src/load_trades.py "C:\path\to\NinjaTrader Grid.csv"
```

The original script performs the raw-to-core INSERT itself. **Do not run `sql/core_transformations.sql` as a setup step**; it is a reference copy of that inline SQL.

Run the loader again with the same file to see the duplicate-file skip. The sample contains 24 fully synthetic rows; keep real exports in the ignored `data/` folder.

## Group and analyze trades

Install your supplied view after the core table exists:

```powershell
psql -v ON_ERROR_STOP=1 -f sql/trade_grouping.sql
psql -v ON_ERROR_STOP=1 -f sql/analysis_queries.sql
```

The view is `analytics.grouped_trades`. It keeps each execution row and adds `group_number`, `group_start_time`, `trade_group_key`, and `direction_group_number`. The view updates as the underlying core data changes; no refresh command is needed.

**Grouping remains work in progress.** This is your current query, preserved as supplied. It groups by direction and overlapping time intervals, including the `entry_time >= previous_max_exit` boundary. It does not inspect A–E or scale-entry names, and it does not separate accounts, instruments, strategies, or files. The earlier case where a seven-record group was merged with later entries has not been verified as resolved. See [project notes](docs/project_notes.md).

## Tests

```powershell
py -m unittest discover -s tests -v
```

Database tests are skipped unless a disposable test database is configured. See [validation.md](docs/validation.md) for the full test setup and results.

## Publish to GitHub

Create an empty GitHub repository, then run these commands from this folder. Replace the example remote with your own repository URL.

```sh
git init
git add .
git status
git commit -m "Add NinjaTrader trading ETL project"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/trading-etl.git
git push -u origin main
```

## Author

**Jude King**
