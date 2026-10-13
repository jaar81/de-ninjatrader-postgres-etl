# Sample data

`sample_trades.csv` contains 24 entirely synthetic execution records. `SIM_PORTFOLIO` and `SyntheticExample` are invented account and strategy labels; the prices, results, and timestamps are illustrative.

The sample includes a UTF-8 BOM, the trailing blank header/field seen in NinjaTrader exports, quoted thousands separators, accounting-style losses, and both AM/PM and 24-hour timestamps.

Three example batches each contain original A–E entries and Scale C/D/E entries. Two are Buy batches at separate times and one is a Sell batch. These eight-record examples do not reproduce the historical seven-record grouping issue or prove that grouping is complete.

The loader should insert 24 raw rows and 24 core rows on the first run. Loading the exact same bytes again should be skipped.
