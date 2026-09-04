# Pre-registration: is the published fixture difficulty a pre-season value?

Written **2026-08-19**, before the 2026-27 season starts and before any outcome exists. The
comparison, the thresholds and what each answer licenses are all fixed here so that none of
them can be chosen after the numbers arrive.

## Why this measurement exists

`opponent_projection_study` measured the largest single fixture effect in this repository:
an adjustment built on the platform's published difficulty rating improved realized squad
points by **+1.74 per gameweek** [+0.52, +3.03], positive in every judged season — roughly
+64 points a season, second only to the chips.

It was ruled inadmissible, not disproved. The archive stores one difficulty value per club
per venue per season with no capture timestamp, and in 2024-25 that value tracks the season
it describes (+0.940 against the table) far better than the season before it (+0.372). A
rating written down after the fact is not a pre-match feature, and 2024-25 was also the
season with the largest measured gain — the pattern contamination produces.

The archive cannot settle this. A live season can, and only from evidence that expires.

## The evidence, pinned before it could expire

`docs/preseason_fixture_difficulty.json` records capture
`fpl-live-20260816T081259Z-e44ade0095e5`, taken **2026-08-16T08:12:59Z**:

- 380 fixtures, 760 fixture sides, all 20 clubs, all 38 gameweeks;
- every side carries a published difficulty (distribution 2:209, 3:342, 4:171, 5:38);
- **130.8 hours before the first kickoff** (2026-08-21T19:00:00Z), and 129.3 hours before
  the first deadline (2026-08-21T17:30:00Z);
- no fixture finished, and the snapshot's payload checksums and fingerprint are stored
  alongside, so an edited capture cannot later be passed off as this one.

`build_preseason_record` refuses to build a record from a capture at or after the first
kickoff, and refuses one carrying a finished fixture. That refusal is the reason this
document can be trusted a year from now.

The record also notes what the platform had **not** published: `strength_attack_*` and
`strength_defence_*` are zero for all 20 clubs, `strength` is null, and only the coarse
`strength_overall_home/away` (a 1–5 scale) is filled. A finished season's archive carries
those same fields populated on a thousand-point scale. Whatever the archive's strength
columns are, they are not what was published in August — that comparison needs no waiting
and is already recorded.

## The two hypotheses

- **H0 — the rating is static.** What the platform published on 2026-08-16 is what the
  archive will store for 2026-27. The 2024-25 correlation anomaly then has some other
  explanation, and `fixture_difficulty` remains a legitimate pre-match feature.
- **H1 — the rating is revised.** The published value moves during the season as form
  reveals who is strong. A single archived value is then a late snapshot for every season,
  and every development-season result that read `mean_fixture_difficulty` or
  `minimum_fixture_difficulty` is measuring partly with hindsight.

## The comparison, declared

`compare_to_later` joins on `(season, fixture_id, team_id, is_home)` — the fixture and the
side of it, so a re-scheduled fixture keeps its identity — and reports how many of the 760
recorded sides carry a different rating.

Two readings settle it, and the first arrives long before the second:

1. **In-season drift.** Compare the record against a capture taken later in the season.
   This is one command per week and needs no new code:

   ```
   python -m scripts.record_preseason_difficulty --compare <later-snapshot-id>
   ```

2. **End-of-season identity.** Once the archive carries a finished 2026-27, compare the
   record against the archive's own fixture table. This is the reading that speaks directly
   to the development seasons, because it is exactly the object those studies read.

## The thresholds, fixed now

| Observation | Conclusion | What it licenses |
| --- | --- | --- |
| **0 of 760 sides changed** at every reading through the season | H0 holds for 2026-27 | `fixture_difficulty` stays a pre-match feature; the 2024-25 anomaly needs a separate explanation before the +1.74 effect can be believed |
| **1–37 sides changed** (up to 5%) | Marginal | The column survives as a feature, but any study leaning on it must say so and report the affected share |
| **38 or more sides changed** (over 5%) | H1 holds | The archive's single value is a late snapshot; `features/fixtures.py` must shift or drop the column on development seasons, and every result that read it is re-run |

Five per cent is chosen as a threshold, not discovered: a rating revised for one club's
worth of remaining fixtures would exceed it, and random noise in a transcribed integer
cannot reach it. It is recorded here so it cannot be adjusted after the fact.

## What this does not do

- It says nothing about whether the difficulty rating is *useful*, only whether the archived
  value was knowable in advance. Even under H0, the +1.74 effect still has to survive being
  re-measured on a season where the pre-season value is known to be pre-season.
- One season is one observation. H0 holding for 2026-27 does not prove the archive was clean
  in 2024-25; it removes the most likely explanation for why it was not.
- The ruling on `features/fixtures.py` belongs to the data side either way. This produces
  evidence, not a patch — see `docs/opponent_rating_handoff.md` and the entry in
  `docs/data_followups.md`.

## Owner and schedule

Measurement side. The record is written; the weekly comparison starts with the first
in-season capture and costs one command. Nothing here touches `prediction/`, `features/`,
`data/` or the live path, and no locked holdout is read.
