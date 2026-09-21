# Top 100 effect reader

Instrument only, implementing [the frozen protocol](top100_effect_prereg.md) for #749 M8.
No real reading was taken in this change. Building this script is not authorization to
run it early, between checkpoints, or again after seeing an answer.

At the separately authorized settled checkpoint:

```text
python -m scripts.measure_top100_effect --season 2026-27 --through-gameweek 12 --data-root <data>
```

GW20 uses `--through-gameweek 20` and writes a different immutable JSON/Markdown pair.
Exports default to `<data>/../artifacts/phase_b`; `--evidence-root` can identify their
existing directory. No solver, fetch, calibration, projection construction or publication
runs. The newest capture must belong to 2026-27 with exactly the requested latest settled
week; all weeks from GW5 must be checked and finished. A later settled week refuses the
earlier checkpoint instead of replaying it. Existing output refuses before input reading.

The ledger's exact projection fingerprint and capture select the player-level base, with
no external uplift. The export must pass `apply_elite_evidence` for that capture; its
adjusted output is discarded. If several exports are eligible, the latest pre-capture
generation is selected, with ties refused. Missing player support is zero; missing player
metadata or outcome excludes the week. No GW4 replay is included.

Plan-level reading starts at GW6. `select_record` checks both capture and publication
times and selects the latest publication before the deadline. The primary slice is plain
`saf-puan`, window 1, no rival or managers-word variant, one pair per member/weight/week.
Both arms must be in the same immutable record; its own unadjusted handoff and export must
also pass. No GW5 plans are reconstructed. Official autosubs, vice captain, chips and hits
come from `score_recorded_advice`. Pitch ordering is cosmetic, but bench order, vice,
transfers, chip and hit differences count as changed plans. Missing price is counted,
never filled with zero or used for a different-population price mean.

Player statistics use within-week/position fixed effects and within-week/position top-40
ranking with player ID as the deterministic tie break. Both all and appeared subsets are
reported. Intervals use 2,000 whole-gameweek bootstrap draws, seed 0; no intervals below
six weeks and no finite interval if any bootstrap draw has an unidentified denominator.
Members and weights do not multiply the effective sample. A weight estimate is descriptive,
never fitted back into a policy. Eight weeks make a rough interval; menu-sized effects of
tenths of a point cannot be established by these readings.

Outputs keep capture/projection/export identities, hashes of member records, exclusions
and reason stages, without private paths or member addresses. After an authorized real
reading, its JSON/Markdown pair must receive a measurements-index row before commit.
Synthetic arithmetic, guard, identity, official-scoring and full-run fixtures are the
validation here; live archive completeness and future checkpoint results remain unverified.
