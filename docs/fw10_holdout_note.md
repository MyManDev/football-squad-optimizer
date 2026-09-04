# fw10 locked holdout: what it decided, and what it does not license

The single shot has been taken. `docs/fw10_holdout.json` and `docs/fw10_holdout.md` are the
run; this note is the reading, the limitations the plan required, and the discipline that
follows.

## The result

**`fw10-bw0` was not promoted.** `fw05-bw0p1` remains the operational control.

| | development (147 folds, 4 seasons) | locked holdout (37 folds, 2025-26) |
| --- | --- | --- |
| paired mean difference | **+2.728** | **+1.405** |
| 90% interval | [0.762, 4.544] | **[−2.622, 4.000]** |
| seasons positive | 4/4 | 1/1 |

Both promotion gates, and which one failed:

```
passes_feasibility          true    37/37 folds feasible
passes_mean_improvement     true    +1.405 clears the 0.5 points/GW threshold
passes_confidence_interval  false   lower bound -2.622 does not clear zero
eligible                    false
```

So the challenger did **not** reverse on the holdout. Its point estimate stayed positive and
roughly halved, and it cleared the effect-size gate. What it failed is the confidence gate: on
one season the interval is wide enough to contain zero.

It also turned over less squad — 4.94 against the control's 6.67 mean turnover — which is not a
gate and is recorded only because it is in the artifact.

## What this closes

The plan wrote the not-promoted branch before the run: *"the control stays `form_window=5`; the
result is recorded and the fw10 hypothesis is closed unless materially new development evidence
appears. No re-runs, no threshold adjustments, no 'one more look'."*

That holds. The holdout is spent. **fw10 is closed.** A wider interval is not a reason to
re-run, a positive point estimate is not a reason to promote anyway, and 0.5 was the declared
threshold before anyone saw this number.

## Limitations

**Prior exposure of the holdout season.** Recorded rather than hidden, as the plan required:
2025-26 was scored by earlier sprint benchmarks of other layers, so it is not a pristine test
set for the repository as a whole. It was unspent for *this* policy decision, which is the
claim the gate rests on, and it is now spent.

**A coverage read before the run.** I read the `GW` column of
`data/raw/vaastav-fpl/data/2025-26/gws/merged_gw.csv` — row count and gameweek coverage only,
38 gameweeks with none missing, 29,757 rows — to confirm the holdout was a complete season
before we spent it. No points, no candidate, no comparison. It carries no information about
fw10 against fw05, but it is a read of the holdout file and belongs on the record rather than
in my head.

**One season is 37 folds.** The confidence gate is the one that failed, and the holdout has a
quarter of the development population. Nothing here says the gate was wrong — it was declared
in advance and it did its job — but a design that requires a two-sided interval to clear zero
on a single season will fail some real effects. **That is an observation for the next
pre-registration, not a reason to revisit this one.** Whether a one-season holdout can support
that gate is a question to settle before the next candidate is frozen, when nobody knows which
way it would cut.

## Provenance

```
repository_commit    0a45769a22d73da2a2b79347291f0750be9fa182
working_tree_dirty   false
screening fingerprint d07f292f799a0e44acd725fd9260c2184e29fbd2ef3030a656f986b3e3cb9388
configuration        1072c1829995473eb89a8a74c8cf61bb80151d410c0f3e5c8ebada2fa1c4e98d
archive commit       8c97b2adb123863c3dd581e730f1360e89815ac2
development_seasons_accessed  false
python 3.11.0 · ortools 9.15.6755 · pandas 3.0.5 · Windows-10-10.0.26200
```

`development_seasons_accessed: false` is the run's own statement that it scored the holdout and
nothing else. Three owners approved on #168 before it ran, each as a comment; the tree was clean
at the commit above; and the command, the environment and the outputs were archived together as
precondition 3 required.

## What follows

The operational control is unchanged, so nothing downstream needs re-deriving — the
uncertainty and scenario calibrations stay as they are, and the GW1 decision already recorded
was made under `fw05`-equivalent settings.

One sequencing consequence: the Route A declaration was deliberately deferred so it would be
written against the post-holdout control rather than chase a moving target. That control is now
known to be unchanged, so the declaration can be written against it.
