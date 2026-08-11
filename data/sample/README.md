# Synthetic sample data

`raw_player_gameweeks.csv` is **entirely synthetic**. No third-party dataset is
redistributed here, and no external provider's schema is implied.

It is generated deterministically from fixed arithmetic patterns — no random
seed involved — by:

```bash
python -m scripts.generate_sample_data
```

`tests/unit/test_sample_data.py` asserts the committed file still matches the
generator, so the two cannot drift apart.

## Shape

288 rows: 36 players (6 teams x 1 GK, 2 DEF, 2 MID, 1 FWD) across 8 gameweeks of
season `2025-26`. The pool satisfies the optimizer's default squad quotas and its
three-players-per-team limit, so it can drive an end-to-end run.

## Deliberate rawness

The file is *raw-shaped*, not canonical, so it exercises the ingestion path:

- fictional source column names (`gw`, `player_ref`, `pos_code`, `price`, ...);
- positions as numeric codes `1`-`4` rather than `GK`/`DEF`/`MID`/`FWD`;
- prices as decimal strings in whole units (`5.5`), not integer tenths;
- rows in a deliberately non-canonical order;
- one column (`ingested_at`) that maps to nothing and must be dropped.

Values are non-monotone and out of phase between players, including benched
gameweeks with zero minutes and gameweeks with negative points. Constant or
uniformly increasing data would make leakage tests vacuous: a shifted and an
unshifted rolling mean look identical when every gameweek is the same.

The file is intentionally clean enough to flow end to end. Malformed cases
(duplicate keys, negative prices, invalid positions, missing values) are built
in memory by test fixtures instead, so this file stays a working example.

## Local real data

Real historical datasets belong in `data/raw/`, which is git-ignored. Do not
commit third-party dumps.
