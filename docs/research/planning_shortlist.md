# Fixed forecast shortlist for bounded planning

Measured on 28 September 2026. Development evidence only; not realized FPL returns.
The fixed rule was recorded before results: retain holdings and required IDs; union
the top eight forecast players and cheapest five in each position in every week.
It is a heuristic subset, not dominance elimination. All selected players keep
their complete forecast and price paths. Tie breaks use player ID. No outcomes,
hyperparameter sweep, new solver budget or production default are involved.

The inputs are the same frozen CONTROL forecast, constructed squad, bank 1 and
one free transfer as `football_planning_replay.md`, not an owner's current state.
There are no chips. Both deterministic arms use the existing feasible-hold guard,
120 wall seconds and 60 deterministic units plus the same hold probe. Recourse
uses one proposed action plus hold and the old equal-probability +/-30% future
forecast stresses; those are not calibrated information probabilities. It makes
multiple solves, so total method costs are not matched. Each case is run once.

| Window | Method | Players | Proof status | Expected net | Hits | Seconds |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | full | 667 | OPTIMAL | 165.83666 | 0.0 | 20.840 |
| 3 | shortlist | 74 | OPTIMAL | 165.83666 | 0.0 | 1.489 |
| 3 | recourse | 74 | OPTIMAL_RESTRICTED_MENU | 167.86007 | branch-specific | 3.778 |
| 5 | full | 667 | FEASIBLE | 274.333657 | 0.0 | 36.594 |
| 5 | shortlist | 83 | FEASIBLE | 278.945934 | 0.0 | 38.492 |
| 5 | recourse | 83 | FAILED | None | branch-specific | 37.469 |

## Interpretation

Three-week deterministic utility matches the proved full-roster optimum; the
restricted recourse utility also reproduces the earlier full-roster menu result.
The five-week restricted deterministic solve improves the feasible forecast
utility, but is not proved optimal even within the subset. The full-roster solver's
bound remains the relevant bound for a full-roster claim. A restricted solver's
bound cannot certify excluded players. Five-week recourse still refuses an
unproved prerequisite; this is a failure, not an improvement hidden by fallback.

These are promising compute/utility observations on one previously used capture,
not a season-policy win or a deployment gate. Do not enable shortlisting as the
member default from this replay. Before that, compare across independent captured
squads, keep/avoid preferences, chips, 1/3/5-week windows and Top100 objectives;
retain the full-pool incumbent and report restricted proof scope explicitly.
The historical hold-protection implementation already serves the production path.

The JSON companion preserves protocol, input/source hashes, diagnostics and every
case, including failures. `scripts/measure_planning_shortlist.py` reproduces this
comparison from the immutable prior study directory into a new output directory.
