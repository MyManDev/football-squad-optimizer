# Route A candidate declaration

Issue #88 · candidate `opponent_signal_rate_candidate_v1` · contract `candidate_change_declaration_v1`

**Frozen before the run, not after.** The fingerprints below are computed from the same typed objects the formal run will use, so what is reviewed is what executes.

## The one thing that changes

`expected_points_rate`. The expected-points rate reads two more inputs: the fitted Dixon-Coles attacking and defensive signals for the player's own club at that gameweek, joined by (season, gameweek, club) from the walk-forward signal frame. Everything else the rate already read is unchanged, and the signal enters as data rather than through any shared feature contract.

| | |
| --- | --- |
| rate inputs before | `points_per_90_last_6`, `appearance_rate_last_6`, `minutes_per_appearance_last_6`, `fixture_count`, `home_fixture_count` |
| added | `rating_attacking_signal`, `rating_defensive_signal` |
| window | 6 |
| ridge alpha | 1.0 |
| minimum training rows | 500 |

Both added columns are the **player's own club's** row for that gameweek, and both
already account for the opponent because that is how the rating produces them:
`rating_attacking_signal` is the club's own expected goals in the fixture, and
`rating_defensive_signal` is the chance that club concedes nothing. Higher is better
for the player's own return in both cases.

## The input, bound rather than described

- produced by `scripts/build_opponent_signal.py`, contract `opponent_signal_v1`
- grain `season/gameweek/club`, joined on `season`, `gameweek`, `club`
- **frame fingerprint** `8d977552f638a53c9be3cd7960a3009344cd04c9538bcdf416727f81e3342624`
- the formal run **re-derives** the frame rather than reading a stored artifact, and
  must reproduce that digest. A mismatch means the input moved, and a moved input is a
  different candidate.

Admissible because it is fitted walk-forward with as_of set to the target gameweek's first kickoff; not the archive's post-hoc fixture_difficulty (#152) and not the published 1-5 rating (#137).

## The stop condition, and the quantity it gates

Expected signs, stated **before** the fit:

| input | expected pooled coefficient |
| --- | --- |
| `rating_attacking_signal` | **positive** |
| `rating_defensive_signal` | **positive** |

> Route A stops if either declared signal's pooled coefficient fails to be positive with its 90% interval excluding zero. The gate is on the pooled coefficient because that is the parameter the model estimates; per-position slopes are recorded as diagnostics and gate nothing. Both clauses are evaluated once, on the formal run, and neither the expected sign nor the interval level is revisited afterwards.

The reasoning behind the expected sign, because the reasoning is the commitment: a club
expected to score more gives its attackers more to score, and a club more likely to keep
a clean sheet gives its keeper and defenders the clean-sheet points and its midfielders
the one-point version. Neither channel harms the other positions -- it does less for
them -- so pooling across positions should not cancel either coefficient.

That is also why S2's per-position slopes came out mixed (GK +0.262, DEF +0.228,
MID -0.041, FWD -0.042 -- `docs/opponent_rating_handoff.md`). Those were fitted against
a single conflated difficulty integer, which cannot be favourable to attackers and
defenders at once, so a pooled fit on *that* would average opposing effects toward
nothing. **Separating the two channels is the substantive difference between Route A and
what S2 measured, and it is the claim this run tests.** If either coefficient returns
negative or straddling zero, the claim is wrong and Route A stops.

Per-position slopes are recorded diagnostics, not gates. If per-position structure
turns out to matter, the remedy is declaring a per-position model, not adding a
per-position gate to a pooled one -- and not after results exist.

## What does not move

Shared contract constants moved: **none**.

The signal joins as data, so the measurement needs no change to
`FEATURE_GENERATION_CONTRACT_VERSION` or `LEARNED_RATE_FEATURE_CONTRACT_VERSION`.
Route A carries its own identity
(`route_a_opponent_signal_rate_v1`) instead. This keeps #43's pending
declaration fingerprint valid today, and makes an eventual bump a reviewed promotion
act sequenced against #43 rather than a side effect of measuring.

Frozen components, none of which the candidate may touch:

- `expected_minutes_stage`
- `cold_start_ladder`
- `availability_post_processing`
- `two_stage_combination`
- `feature_window_mapping`
- `shrinkage_weights`
- `opening_price_prior`
- `development_fold_set`
- `baseline_control`
- `ridge_reference`
- `optimization_contract`
- `budget_and_formation_constraints`
- `promotion_gates`
- `evaluation_objective`
- `learned_rate_training_contract`
- `shared_feature_contract_constants`

## Fingerprints to freeze

```
declaration_fingerprint              29deea10bf176b59b5a4c9107008e8870ebcb5d685077fc3aa6e1142a6db4036
benchmark_configuration_fingerprint  01bd220fbcb23e467f9945f243528fe73cf53af7cb092cd5db049cc28bb4cbf6
signal frame_fingerprint             8d977552f638a53c9be3cd7960a3009344cd04c9538bcdf416727f81e3342624
```

A changed candidate is a new candidate with a new fingerprint. If any of these three
moves, this declaration describes something that is not being run.

## The control this was written against

`fw05-bw0p1`, and the fw10 locked holdout did not
promote its challenger, so the control is unchanged. This declaration was deliberately
written after that run rather than before it, so it does not chase a moving control.

Development seasons: 2021-22, 2022-23, 2023-24, 2024-25. Locked holdout accessed: **False**. Formal run completed: **False**.
