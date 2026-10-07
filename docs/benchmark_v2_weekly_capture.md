# Private weekly Benchmark V2 capture

Issue #1016 step 1 adds explicit research capture options to the weekly command.
Both are off unless the owner enables them. The owner must approve this PR before
merge and run the collection himself under the weekly-operation rules in #1012.

`--benchmark-freeze` copies the already frozen primary paper-squad ledger decision
for the requested season/week, its exact decision-time `fpl-live` pool and the
original pre-deadline `fpl-top100` cohort into the ignored private store
`artifacts/benchmark-v2-captures`. It then writes an immutable
`fpl-benchmark-decision` receipt before the deadline. It binds the original capture
ids, fingerprints, system-decision digest, bench order, vice-captain and the current
configured ownership-template budget of 1000 tenths, club limit 3 and scale 1000.
It does not decide a squad, alter an existing decision, infer a late bench order,
fit a projection or manufacture a missing paper decision. If the owner has not
already made the primary decision, the receipt states unavailable.

The existing Friday Top-100 picks stage reads N-1 for projection evidence. It cannot
serve as the benchmark's target-week picks. After settlement, the new
`--benchmark-picks-freeze <freeze-id>` option collects target-week picks and histories
only for the original 100 members of that explicit freeze. Repeat the option to
collect several explicitly named pending weeks. No current standings are consulted,
no member is replaced by rank 101, and unreadable members are counted as missing.
The bootstrap must state finished and data_checked for that target deadline before
any member's picks are fetched. The receipt also retains the target's official live
event points and minutes in a separate `fpl-live` outcome capture in the same store.
Collection does not calculate a benchmark score or admit a week to the live reading.

The owner can perform this collection alongside the Tuesday settle without calling
the publication workflow:

```powershell
python -m squadopt.platform.benchmark_capture --snapshot-root <workspace>/artifacts/benchmark-v2-captures --freeze-snapshot <fpl-benchmark-decision-id>
```

Use the first successful completed collection for each frozen week. The weekly
journal retains immutable output ids and hashes on resume. The reader's explicit
manifest uses the retained original decision and cohort, the decision-freeze id,
the picks id and the outcome id in the picks receipt. Do not select a later capture
after inspecting results. No archive or locked-holdout store is enumerated or opened.

Research receipts stay in their own store so they cannot change a product capture
inventory or the earlier settled-outcomes stage's directory fingerprint. They are
journalled privately and do not emit product run-log stage events. The published
builders and their inputs are unchanged. An unavailable research input is recorded
privately and does not stop the normal publication stages. The default weekly
declaration and stage plan are unchanged when both options are omitted.

The first finish box still needs the owner's merge approval and evidence from the
next real weekly run. The GW6 Friday run is due on 2026-10-09; its target deadline
is 2026-10-10T10:00:00Z. No real weekly run or FPL network request was made to develop
this addition. The live reader and its eventual result PR are separate steps.
