# Five-free-transfer accounting preflight

This read-only preflight starts at `0078a43c6207026cfb506d94806101bdf7c6dc50` and does
not change planner code or the Phase 1 inputs/records. The requested fault is the
`Invalid deterministic-work accounting for expected windows.` exception reported for
GW8/GW9 entry 3832237 under the separately frozen baseline-forecast experiment.

## Saved served-path probe

The available local ready bundle is capture `fpl-live-20261002T104314Z-8b70515b9b31`,
GW6. The probe validates its source snapshot, saved baseline handoff, football forecast,
ready marker, participation components and captured entry through the same readers used
by member advice. The entry has **five free transfers** and **five tenths bank**. It uses
the actual selected `fixture_football_candidate` forecast and calls `plan_transfer_horizon`
with 60 deterministic units, 1,800 seconds and linearization level 2.

The selected route is **observed-information**, not the expected-window wrapper. The
result is **FEASIBLE with a complete solution** and the requested exception is not raised.
The [record](llmopt_window_budget_probe.json) pins the two saved artifact hashes, input
identity, selection and route. This one probe neither establishes absence of the fault
nor tests the alternative expected-window branch by disabling captured information.
The probe does not fetch data, fit a forecast, contact a service or change a serving flag.

Reproduce with the same saved archive, from this checkout, with `PYTHONPATH=src`:

```text
python -m scripts.probe_expected_window_capture --data-root SAVED_REPOSITORY --snapshot-id fpl-live-20261002T104314Z-8b70515b9b31 --entry-id 3832237 --output artifacts/window-budget-probe.json
```

## Unfinished

The served football forecast and ready bundle for the two Phase 1 captures
`fpl-live-20261023T111647Z-a2cd55fde426` and `fpl-live-20261030T070058Z-8b2a93c0babe`
are not available in the inspected local archive. Substituting their baseline handoffs,
renaming a forecast or removing observed information would not reproduce served behaviour.
Therefore there is no demonstrated served-path regression test and no production fix.
The other eighteen Phase 1 results were not rerun: all product code and frozen evidence
remain byte-identical, rather than being replaced with a new measurement.

Source inspection suggests a separate accounting risk: segmented construction apportions
nominal caps and the final guarded solve retains its nominal 90% even when construction
consumes more than its share. This is a hypothesis, not a verified served-path diagnosis.
No tolerance was enlarged and no further work was authorized by the hypothesis itself.

## Morning decision

Provide the exact two served forecast bundles if this fault should be pursued against
those captures. The conservative choice is to preserve product behaviour until that path
is reproduced. Run-budget enforcement and net-point preferences do not depend on changing
this expected-lineup allocation; package-search acceptance must retain this open limitation.
