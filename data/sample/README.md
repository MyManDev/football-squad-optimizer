# Synthetic sample data

Everything here is **entirely synthetic**. No third-party dataset is
redistributed, and no external provider's schema is implied.

Each file is generated deterministically — no random seed involved — and a test
asserts the committed file still matches its generator, so the two cannot drift
apart.

| File | Generator | Test |
| --- | --- | --- |
| `raw_player_gameweeks.csv` | `python -m scripts.generate_sample_data` | `tests/unit/test_sample_data.py` |
| `club_news_v1.fixture.json` | `python -m scripts.generate_club_news_fixture` | `tests/unit/test_club_news_fixture.py` |
| `club_news_coding_v1.fixture.json` | `python -m scripts.generate_club_news_coding_fixture` | `tests/unit/test_club_news_coding.py` |
| `entry_registry_v1.example.json` | hand-written shape example | — |

## `raw_player_gameweeks.csv` — shape

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

## `club_news_v1.fixture.json` — the hard cases, written down

It stands in for a club's own team-news page and for the model that reads it, so
the identity join, the rotation evidence artifact and the weekly step can all be
built and tested with **no API key, no network and no captured club bytes**.
`FixtureClubNewsProvider` in `squadopt.data.sources.club_news` serves it, and
connecting the real thing later changes one construction site.

It is not a smoke test. It is the specification of the states something
downstream has to keep apart, and it carries one of each:

- a document dated to the second, one dated to the **day only**, and one with
  **no dateline at all** — a day is never rounded up to an instant, and an
  absent dateline is never filled in with the instant we fetched the page;
- a roster player the model says **nothing** about (absent from the claims), a
  player whose club **no document was read for**, and a player his club's own
  document **says nothing about** — three different states, and none of them
  means he will start;
- every value of the closed disposition vocabulary except `not_addressed`, which
  is expressed by that absence;
- a quotable span containing a literal `%`, which the published-surface guard
  forbids absolutely, so the span is refused rather than rewritten;
- a paraphrase containing a `%`, and another containing a likelihood word —
  refused, not cleaned up: a paraphrase is *our* sentence;
- a bare surname two players in one club share, and a name matching nobody, so
  the join refuses instead of guessing;
- four responses that break the response format four different ways, so a parser
  refuses rather than coerces.

`club_news_coding_v1.fixture.json` is derived from this file: every quote it carries is
cut from this fixture's document bytes at the offsets it declares, so the two agree by
construction.

Real captured club documents belong under `data/snapshots/`, which is
git-ignored, and no byte of one is in this repository.

## Local real data

Real historical datasets belong in `data/raw/`, which is git-ignored. Do not
commit third-party dumps.
