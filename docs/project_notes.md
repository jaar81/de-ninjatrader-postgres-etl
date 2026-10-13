# Project notes

## What this export preserves

This export was prepared on October 13, 2026. `src/load_trades.py` is an unchanged copy of the original file supplied by Jude King. It retains the existing functions, inline SQL, comments, connection settings, output messages, and command-line usage.

`sql/trade_grouping.sql` contains the full `analytics.grouped_trades` query supplied with this revision. Its logic has not been replaced or expanded. The table-creation scripts are compatible bootstrap definitions because the original database DDL was not supplied; they are intended for a new database only.

## Current grouping logic

1. Start with core rows that have entry and exit timestamps and an exit at or after the entry.
2. Treat the same entry timestamp and direction as a batch, using its latest exit.
3. Find the latest exit across all earlier batches in that direction.
4. Start a new group when no prior exit exists or the entry is **at or after** that prior maximum exit.
5. Number the groups within each direction and calculate their start times.
6. Join the batch results back to the original rows. Add a global number using `DENSE_RANK`, a timestamp/direction key, and the original per-direction number.

The intended business model connects original A–E entries and later scale-ins. The stated rule is that the current batch fully closes before the next original batch begins in the same direction. The SQL uses time intervals to approximate this; it never checks entry names or explicitly assigns scale-in ownership.

The earlier discussion reported a group with about 10/11 records where that particular group should have had seven. Receiving the full current SQL does not establish that this case is fixed. The included synthetic examples test selected mechanics, not that historical case.

## Limits to keep in mind

- **Grouping scope:** the query partitions only by `market_position`. It can combine records across accounts, instruments, strategies, and source files. Filtering the view afterward does not undo those group assignments.
- **Changing history:** global `group_number` values can change when earlier data is added. A bridging interval can also change a group's start time and `trade_group_key`. These are computed view values, not permanent stored identifiers.
- **Excluded rows:** invalid/missing timestamps are filtered; a null direction cannot match the final equality join.
- **Display order:** use an outer `ORDER BY` when reading the view. The ordering inside the CTE does not guarantee the final display order.
- **File duplicates:** SHA-256 prevents repeat loads of identical bytes. Different or overlapping exports can still repeat underlying executions.
- **Original input contract:** the exact English 19-column header is required. One trailing blank field is handled; completely empty records are rejected by the original row-width check.
- **Numbers and timestamps:** the original SQL keeps `NUMERIC(18,2)` and timezone-less entry/exit timestamps. Price precision beyond two decimals can be rounded. The source timezone was not established.
- **Accounting notation:** parentheses-to-negative conversion is present for Profit and Cum. net profit. Other numeric fields retain their original dollar/comma cleanup.
- **Profit:** analysis uses profit as exported and shows commission separately. Whether the export already includes commission is unconfirmed. Do not sum cumulative net profit.
- **Running loads:** this original version checks the hash without adding a concurrency lock. Run one load at a time and leave the source file unchanged while loading.

Keep real exports, passwords, and database backups out of the public repository. The sample file is entirely synthetic.
