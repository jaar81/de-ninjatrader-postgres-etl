# Implementation notes and provenance

Prepared on October 12, 2026 from the available project conversations: **Resume Documentation Advice**, **PostgreSQL / Python Project**, **Explain Psycopg Commands**, and **Group trade entries**. The project reference folder contained no files. The latest long loader response was partially truncated; the preceding accounting-conversion response and the explicit timestamp patch supplied the missing behavior. The resulting repository is a reconstruction, not a claim that an original source checkout or live database was recovered.

No private conversation exports, screenshots, database credentials, or original trading rows are included.

## Recovered behavior versus packaging decisions

| Area | Evidence and treatment |
| --- | --- |
| Ingestion status | User reported the script working. Preserve that historical status separately from tests of this package. |
| Raw and core tables | Recovered loader names `raw.ninjatrader_trades` and `core.trades`. Raw source fields are text; conversions occur in SQL. |
| Control table | `control.file_loads` lookup by SHA-256 and success insertion of filename, hash, raw count, and core count. |
| Source metadata | `source_file`, `source_file_hash`, `source_row_number`; `loaded_at` is passed from raw to core. |
| CSV layout | Exact 19-column header, UTF-8 BOM handling, one trailing empty header/value accepted. |
| Loading | Psycopg 3 row-wise COPY, then core INSERT filtered by file hash, then control INSERT, within one transaction. |
| Duplicate prevention | Full-file SHA-256 in 8,192-byte chunks; core `ON CONFLICT (source_file_hash, source_row_number) DO NOTHING`. |
| Timestamp patch | Explicit AM/PM detection uses `MM/DD/YYYY HH12:MI:SS AM`; otherwise `MM/DD/YYYY HH24:MI:SS`. |
| Monetary conversion | Dollar signs and commas removed. Accounting parentheses were confirmed for `profit` and `cumulative_net_profit` only. |
| Grouping | Partly visible interval-based SQL and an unresolved user-reported overmerge. Full final SQL was unavailable. |
| Table DDL | Original CREATE TABLE statements were unavailable. Types follow the recovered INSERT; identity keys, constraints, indexes and control timestamp name/type are new bootstrap choices. |

## New changes made while packaging

- Extracted the repeated SQL conversion into `core.parse_money`, `core.parse_trade_timestamp`, and `core.load_trades`, installed by `sql/core_transformations.sql`. The Python loader calls that function instead of embedding the entire INSERT.
- Added a temporary input snapshot, so the hashed bytes and parsed bytes match. Large exports require temporary disk space approximately equal to the input size.
- Added a transaction-scoped advisory lock to serialize simultaneous loads of the same hash. The control primary key and raw/core unique constraints remain durable safeguards.
- Added strict currency punctuation and timestamp shape/range checks, blank-value-to-NULL handling, strict CSV parsing, explicit malformed-row errors, and empty-record skipping.
- Made timestamp parsing independent of database-session daylight-saving behavior by parsing and removing the intermediate timezone in UTC. This preserves the displayed source wall-clock value; it does not assert that source trades happened in UTC.
- Added layout-only validation, unittest coverage, synthetic samples, and CI configuration.
- Reconstructed an optional candidate grouping view with documented scope assumptions. Its status remains `experimental_unverified` regardless of whether its SQL executes successfully.

## Deliberately unresolved

**Existing database compatibility.** These scripts are for a new database. `create_tables.sql` deliberately errors if a target table exists instead of silently accepting unknown definitions. Compare your live DDL and plan a migration separately; no live database was inspected or changed while packaging.

**Precision.** The recovered SQL casts prices and financial fields to `NUMERIC(18,2)`. That can round prices for instruments requiring finer precision. Changing it would alter the recovered contract; confirm the required instrument precision first.

**Timezones and sessions.** Source timestamps lack an established timezone. Preserve `timestamp without time zone`; do not derive RTH/ETH or UTC offsets yet.

**Other monetary fields.** Commission, MAE, MFE, ETD, and prices support signed numeric/currency strings but do not accept accounting parentheses in this preserved implementation. If a real export uses parentheses there, the load fails atomically. Confirm the source convention before deliberately extending `parse_money` usage for those columns.

**Header/locale variations.** This package supports the recovered English US-style header and numeric/date formats. It does not guess aliases, decimal separators, other currencies, or localized dates. An unfamiliar layout is rejected for explicit mapping.

**Profit and commission semantics.** The export configuration determining whether Profit includes commissions was not recovered. Reports show exported profit and commission separately. Cumulative net profit is not additive.

**Cross-file duplicates.** Hashing catches identical bytes only. Different exports can repeat the same trades. Analysis queries separate files to make this limitation visible; a future business key needs validation.

**Grouping.** The exact failing records and full final SQL were unavailable. The synthetic sample does not recreate that failure. See [trade_grouping.md](trade_grouping.md) for the current business rule, observed algorithm, reconstructed assumptions, and required validation.

**Operational scope.** No scheduler, rejected-record table, production monitoring, warehouse integration, dimensional model, or dashboard is implemented. No measured performance or business-result claim is made.
