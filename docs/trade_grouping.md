# Trade grouping: experimental and unfinished

The project aims to associate original entry legs and subsequent scale-in entries with the correct logical trade. **This work is not complete.** Standard analysis in this repository uses individual records from `core.trades`; it does not depend on draft grouping results.

In the latest available project discussion, the user reported that a new set beginning with A was still assigned group 1. That group contained about 10 or 11 records and should have contained seven, including the scaled trade. There is no recovered confirmation that this case was fixed. Seven is the expected size of that particular case, not a universal group size.

The confirmed business rule is that all positions in the current original A–E batch must close before the next original A–E batch begins in the same direction. Later C/D/E scale-in entries belong to their original batch. The rolling interval candidate below may not enforce this rule correctly: it does not distinguish an original batch from its scale-ins or establish scale ownership.

## What was recovered

The October 2026 **Group trade entries** discussion and its screenshots establish:

- The raw table is `raw.ninjatrader_trades`. A reference to `raw.trades` was challenged as incorrect.
- An attempted `analytics.grouped_trades` view read raw text timestamps and failed with `function to_char(text, unknown) does not exist`. The user requested using the typed core layer instead.
- The visible algorithm first excluded null timestamps and exits before entries. It batched rows by `market_position` and `entry_time`, taking the maximum exit time of each batch.
- It then calculated the maximum exit over **all preceding batches** in the same direction, using a window frame ending at `1 PRECEDING`.
- A later result showed the same group number for Buy and Sell batches with different group start times. Numbering separately by direction could explain the repeated labels, but the final underlying SQL was unavailable. This is a possible explanation, not a verified diagnosis or fix.

The earlier **SQL Grouping Rows** discussion asked how to assign ordered rows into fixed groups of five. It was a general SQL question and does not establish a fixed-size trading rule. The later **Rearrange SQL Columns** discussion concerned display order, not grouping correctness.

The full assistant SQL bodies were unavailable in the retrieved conversations; the visible SQL fragment ended as the new-group flag stage began. Accordingly, this repository preserves the observed approach but labels the missing continuation as a reconstruction. Conversation exports and private screenshots are not included.

## Optional candidate view

After creating the core tables and installing the core transformations, run the optional script explicitly:

```sh
psql -v ON_ERROR_STOP=1 -f sql/trade_grouping.sql
```

Use the same `PGDATABASE` development-database setting as the README setup. The script creates `analytics.trade_group_candidates`. It does not create or replace `analytics.grouped_trades`. The candidate view is for review only, and `grouping_status` is always `experimental_unverified`.

The implementation adds these **unverified assumptions** to the recovered fragment:

| Choice | Meaning and limitation |
| --- | --- |
| Scope includes file hash, account, instrument, strategy, and direction | Newly added isolation prevents unrelated streams being mixed. A logical trade spanning files will be split; overlapping exports remain a separate problem. This scope was not recovered from the old SQL. |
| Same entry timestamp within that scope means one batch | Preserves the observed approach. Separate entries with identical timestamps can still be combined incorrectly. |
| An entry strictly after the prior maximum exit begins a new candidate | The continuation was reconstructed because the actual flag condition was unavailable. An intervening long-running position can bridge independent entries and overmerge them. |
| Entry exactly at the prior maximum exit stays in the same candidate | Equality is unresolved. Such rows are flagged with `equal_boundary_requires_review`; this behavior requires confirmation. |
| Null timestamps and exits before entries are omitted from candidates | This matches the visible validity filter. It is an exclusion, not a resolved grouping policy; the core records remain available for inspection. |
| Names containing `scal`, exact A–E names, or names ending in Entry A–E receive diagnostic labels | These patterns are newly added review aids. They neither assign scale ownership nor define a reliable boundary. C/D/E scale-ins that use only the letter remain indistinguishable from original C/D/E legs by name alone. |

`group_number` is a running number **within the full scope above**. It starts at 1 for each scope and is not a globally unique trade ID. Never join, aggregate, or count logical trades by `group_number` alone. For review, retain all scope columns and `group_start_time` together. Even those values identify only a provisional candidate, not a confirmed business trade.

`entry_kind` highlights names containing `scal` and named entry legs, accepting both exact letters and names such as `Buy Market Entry A`. A later row named simply C, D, or E may be a scale-in; its name alone will not identify that. `later_a_requires_review` flags an A-labeled row entering later than its candidate's start time. Neither flag is a correction: repeated A records may represent exits from the same original entry, so “every A starts a new group” is also unsafe without validation. Multiple A records at the same timestamp remain an unresolved ambiguity.

## Review before relying on grouping

The SQL file includes diagnostic queries for excluded rows and candidate membership. Review against a manually labeled, sanitized example of the reported problem. Establish which original trade owns each scale-in, the expected number of groups, and exactly which rows belong to each group. Then verify:

1. The reported first group contains exactly its seven expected records, and the subsequent A set starts the correct separate trade.
2. Multiple exits for one A entry stay together; a genuinely new A entry is separated.
3. Scale-ins attach to their intended original entry even when intervals overlap or exits are interleaved.
4. Equality at entry/exit boundaries, missing timestamps, and simultaneous entries follow an explicit rule.
5. Account/instrument/strategy/direction and cross-file behavior match the intended trading context.
6. Any final identifier is stable and unique at the intended scope.

The synthetic sample data demonstrates file parsing and record-level transformations. It is not a recovered copy of the failing grouping case and does not prove the grouping algorithm correct. Unit tests of ingestion and transformation likewise do not certify grouping. Until labeled real-case validation succeeds, keep candidate grouping out of official trade counts, win rates, and other logical-trade metrics.
