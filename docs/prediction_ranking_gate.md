# Prediction gate: ranking, bounded error, paired decisions

M4 of [#749](https://github.com/MyManDev/football-squad-optimizer/issues/749).
Implementation: `src/squadopt/evaluation/prediction_gate.py`, contract
`prediction_ranking_gate_v1`. This is a template for a future preregistered candidate,
not a replacement verdict for already measured candidates and not a production promotion.

## The three clauses

All three must pass. Report each clause even when another fails. Known failure takes
precedence over missing evidence in the overall verdict; otherwise missing evidence is
`insufficient`, never a pass. Require at least two judged seasons. Declare the seasons,
positions, control, eligible rows, pairing and interval construction before measuring.

1. **Primary: within-position ordering.** Compute Spearman against realized points within
   each declared position, per season and pooled, using identical candidate/control rows.
   The unweighted mean of the pooled position gains must be at least **+0.01**. No
   season-position or pooled-position cell may lose more than **0.01**. This stops a large
   position or one improved season from hiding a regression elsewhere. Undefined
   correlations are missing evidence, not zero and not a passing tie.
2. **Error guardrail.** On the declared all-row point population, candidate MAE may rise
   by at most **5%** relative to control, both pooled and in every judged season. This
   admits a small numerical error cost for useful ordering; it does not admit unlimited
   miscalibration. If control MAE is zero, candidate MAE must also be zero. An appeared-row
   reading is a separate diagnostic and cannot substitute for a missing all-row reading.
3. **Paired decisions.** Mean realized candidate-minus-control squad points must be at
   least **+0.5 per decision**; the preregistered paired **90%** interval's lower endpoint
   must be **strictly positive**; at most **one** judged season may have a negative mean.
   Both arms use the same roster, scoring rules and frozen deterministic solver budget.
   The runner must report incomplete pairs and solver statuses rather than select the
   successful arm of a failed pair. An interval spanning zero does not establish a loss,
   but also cannot satisfy this positive-benefit rule.

These thresholds are prospective policy choices, not estimated optimal values. The rank
margin demands more than any improvement's sign; the 5% band is a bounded tradeoff; +0.5
is a practical decision floor, with uncertainty and season consistency independently
required. They were chosen while reading existing aggregate records, **before fitting or
reading folds for the appearance recalibration candidate**. Therefore the historical
exercise below is illustrative, not new confirmatory evidence. M5 must freeze the complete
policy fingerprint and its population before a candidate run. Changing any threshold
changes that fingerprint; it cannot rescue a measured candidate under the same declaration.

## Existing records, without a rerun

Only the committed summaries/aggregate JSON fields were read. No OOF table, raw season,
fold outcome or solver was opened for this comparison. The third record's ranking population
is appeared GK/DEF rows; its result illustrates that population, not an unmeasured full-roster
rank gain. Historical records and their original verdicts remain unchanged.

| Historical candidate | Ranking clause | Error guardrail | Paired decision clause | Template verdict / original status |
| --- | --- | --- | --- | --- |
| `participation_composition`, composed vs uncomposed | Unestablished: no position-rank summary; only one judged season. | All-row MAE 1.0305 vs 1.0303 is inside the band, but one season cannot establish this gate. | Mean −1.405, interval [−3.569, +0.164]; fails the positive-benefit requirement. 26/37 changed squads is not a benefit metric. | **Fails** on the known decision reading; incomplete rank/multiseason evidence stays explicit. Original remains **descriptive, no gate**. |
| `positional_defence` | Passes on its declared appeared GK/DEF population: pooled DEF gain 0.040333 and GK gain 0.060769, macro gain **0.050551**; every seasonal cell improves by more than 0.01. | Pooled all-row MAE 0.985883 vs 0.967740 is inside 5%. Per-season *all-row* MAE is not in the aggregate gate record; its per-season appeared-row MAE cannot fill that hole. Thus **insufficient** for this clause. | Mean −0.519, interval [−1.760, +0.885], two losing seasons: fails. Neither an established loss nor a benefit. | **Fails** despite better ranking. Original remains **fails** under its own different gate. |
| `prior_minutes_level` | Unestablished: no position-rank reading in the record. | Pooled MAE 1.0607 vs 1.0795 is inside the band; per-season all-row MAE is not reported in its gate summary. | Mean −0.218, interval [−0.830, +0.313], two losing seasons: fails. 107/147 ties do not establish benefit. | **Fails** on the known decision reading, with rank/error gaps explicit. Original remains **failed**. No changed-index rerun is permitted. |

Sources: `participation_composition.md:25–29,49–59` and JSON
`decisions.paired_against_uncomposed.composed`; `positional_defence.json` fields
`ordering.readings`, `accuracy.floor_over_surviving_rows`, `decision`; and
`prior_minutes_level.md:14–26` / JSON `decision_gate`. The macro gain above is arithmetic
on two already published correlations, not a newly measured statistic. The implementation
also leaves missing inputs explicit so a future reader cannot turn an illustrative table
into a fabricated passing evidence bundle.
