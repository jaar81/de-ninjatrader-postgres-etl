# Synthetic sample export

`sample_trades.csv` contains **24 invented execution records**. The account `SIM_PORTFOLIO`, strategy `SyntheticExample`, timestamps, prices, profit, costs, and excursion values are examples, not a user's trading history or a performance claim.

The file intentionally includes:

- A UTF-8 BOM and one empty trailing CSV header/field.
- Quoted prices and monetary values containing thousands separators.
- Positive values, accounting-style losses, and negative cumulative profit.
- Both AM/PM and 24-hour timestamps.
- Whitespace around selected text fields, retained in raw and trimmed in core.
- Buy and Sell source labels, original A–E entries, and later Scale C/D/E entries.

Records 1–8, 9–16, and 17–24 illustrate three intended example batches. The two Buy batches do not overlap; the Sell batch is separate. Within each batch, five original entries are followed by three scale entries. These eight-record illustrative batches are **not** the seven-record case reported in the grouping conversation. The source labels are examples; actual scale naming must be verified against the export.

The sample exists to exercise ingestion and typed conversion. Its rows and annotations do not establish complete grouping rules, demonstrate financial accuracy, or validate the unfinished grouping algorithm. The `Bars`, MAE/MFE/ETD, and commission fields are illustrative and should not be used to infer strategy behavior.

Use a non-overlapping collection of exports for analysis. Running the loader on this exact file twice should produce one successful load and one skipped attempt. Modifying the file's bytes creates a different SHA-256 identity.
