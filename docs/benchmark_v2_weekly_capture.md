# Private weekly Benchmark V2 capture

Both research flags default off. `--benchmark-freeze` requires `--decide` or an
existing primary ledger entry before any weekly stage starts. It copies the
verified decision bytes, exact decision-time pool and original pre-deadline
Top 100 into the private immutable store `data/benchmark_v2_captures/`. That
optional tree, including its binding claims, is covered by `scripts/backup_data.ps1`.
It is ignored by git and kept separate from the product snapshot inventory.

The freeze verifies the ledger manifest and decision digest, the live season,
target deadline and scoring fields. The cohort must have been captured while
that target gameweek was open. Exact retained source copies must agree. The
receipt binds the decision and cohort ids and fingerprints, bench order,
vice-captain and configured ownership-template budget, club limit and scaling.
No decision or missing roster input is manufactured by this stage.

One create-once claim per season and gameweek names its binding freeze. Repeated
calls return that claimed id. A picks collection accepts only that claimed freeze;
a caller cannot substitute another freeze for the week. Claims retain their exact
receipt fingerprint and are included among the weekly stage's journalled outputs.

The normal Friday Top-100 picks stage supplies N-1 projection evidence. The
`--benchmark-picks-freeze <freeze-id>` option separately collects the original
100 members' target-week picks and histories after the target is finished and
`data_checked` at the frozen deadline. Repeat the option for distinct pending
weeks. The outcome capture keeps the observed settled bootstrap and that target's
official live event. It does not calculate a benchmark score.

A member counts as unavailable only on HTTP 404. Any other failed read aborts
without a completed picks receipt or claim, so the operator can retry. Completed
receipts record readable and unreadable counts and failure codes, never entry ids
in their diagnostics. The weekly stage value and standalone CLI show those counts.
The first collection with no transport failures gets the immutable picks claim;
later calls return that claimed id without another network collection. No rank-101
replacement or selection of a later completed receipt is allowed.

Collection can run alongside settlement without the publication workflow:

```powershell
python -m squadopt.platform.benchmark_capture --snapshot-root <workspace>/data/benchmark_v2_captures --freeze-snapshot <fpl-benchmark-decision-id>
```

The live reader's manifest must use the claimed freeze and picks ids, their exact
original decision/cohort and the outcome id recorded in the picks receipt.
Unclaimed receipt files left by an interrupted metadata transaction are not binding.
No archive or holdout inventory is enumerated by these commands.

Unavailable stage receipts carry fixed reason codes such as `missing_decision`,
`not_a_decision`, `no_cohort`, `deadline_mismatch`, `late`, `not_settled`,
`missing_freeze` and `transport_failure`. The CLI prints a code without private
exception text. Successful research stages stay out of the member status feed;
a journal refusal emits a generic `research_stage_refused` failure event and
re-raises so a stopped resume is visible. Source or output drift still refuses
resume and needs a new reviewed run. No research flag silently adds a decide step.
The default stage declaration and product plan remain unchanged with both flags off.
