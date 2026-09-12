# Installed weekly operations and recovery

The installed entry point is `python -m squadopt.platform.weekly_operations`.
`python -m scripts.run_week` preserves the existing flags and delegates to it. The
domain planning, preflight, handoff, player evidence, rotation export and settled-outcome
export live in `application`; HTTP capture, process pools, Git publication and execution
journals live in `platform`. The installed runner does not import `scripts`: its `publish`
stage hands `platform.weekly_publish` a typed builder for the site, league and scoreboard
views. The manual `python -m scripts.publish_gameweek_site` path supplies no builder and
still runs the `scripts.build_site`, `scripts.build_league_site` and
`scripts.build_scoreboard` shells in a subprocess (`_legacy_build`).

Use short Windows workspace and handoff roots on hosts with the legacy path limit.
Retained content-addressed paths add directories and a 69-character filename; a
263-character target failed on the acceptance host while the unchanged resume test
passed under a shorter root. This implementation does not enable Windows long paths.

The [weekly runbook](../weekly_runbook.md) remains the authority for the capture target:
**2–3 hours before the deadline**, after previous picks become public. This change does
not invent a recurring clock time. A run records the capture's measured deadline lead and
whether it falls in that window; it does not reinterpret a reused capture as a fresh live
decision or refuse a deliberate replay merely because it is outside the target window.

## Start, observe and resume

```bash
python -m squadopt.platform.weekly_operations --workspace /srv/squadopt \
  --season 2026-27 --gameweek 4 --league 352490 --workers 8 \
  --run-id 2026-27-gw04-decision --decide

python -m squadopt.platform.weekly_operations --workspace /srv/squadopt \
  --status --run-id 2026-27-gw04-decision

python -m squadopt.platform.weekly_operations --workspace /srv/squadopt \
  --season 2026-27 --gameweek 4 --league 352490 --workers 8 \
  --run-id 2026-27-gw04-decision --decide --resume
```

A missing `--run-id` generates and prints one. Every run writes
`data/runtime/weekly/<run-id>/run.json`. Its fixed request includes all configured roots,
the declared source revision and a hash of the actual installed Python package bytes.
Source checkouts must be clean and a supplied revision must equal HEAD. An installed
non-Git workspace needs `--repository-commit <full-40-character-revision>`; this is a
declared build revision, independently bound to the recorded installed-package hash.

The preview defaults to `data/runtime/weekly/<run-id>/preview`, keeping generated views
out of the source tree. `--out` remains available, but choosing tracked output paths can
make the checkout dirty and prevent resume until reconciled. The default requires no such
source exception. `--dry-run` prints the same plan through either command and writes nothing.

Each stage has attempts, timestamps, terminal state, input fingerprints, returned values,
and output byte hashes. Directory fingerprints include membership, so added capture
payloads are changes too. A zero exit without the declared files is failure. The runner
rechecks inputs after work, outputs before completion, and completed outputs on status.
Missing, changed, corrupt or symlink/reparse paths fail closed. A resume must retain the
original request, package identity and stage inputs; completed stages verify and skip work.

An OS ownership lock prevents simultaneous owners of one run; a workspace lock prevents
two weekly runs from overwriting shared aliases together. A separate short metadata lock
excludes journal replacement while status holds a Windows read handle. Status does not
wait for an entire solver stage. OS locks release on process exit; an abandoned running
stage is observed as interrupted, and its attempt is retained when safely resumed.

`--status` reports `not_started`, `running`, `completed`, failure, interruption, uncertain
publication, or invalid artifacts. It returns nonzero for an unsuccessful observed state.
Without an explicit expected time, `missed` is unknown. A configured scheduler can pass
`--expected-at 2026-09-12T15:00:00Z`; missed or late completion returns nonzero. That example
is an input shape, not an adopted schedule. No scheduler, notification channel, target
host, retention policy or freshness/SLO rule is installed by this implementation.

## Capture and evidence boundaries

The selected capture is pinned for handoff, league, status and scoreboard assembly.
Preflight checks the registry, required previous ledger state, chip availability and
reused evidence before collectors run. A live decision requires a capture taken by this
run and execution before its deadline; reused and late decisions remain replay.

Settled outcomes run after capture, before the upcoming decision. They use only captures
at or before that capture's timestamp and export only earlier gameweeks with both required
pre-deadline and finished/checked observations. Missing pairs produce explicit per-run
reports, not invented rows. This exports observational tables; it does **not** settle the
current ledger entry. Ledger settlement remains the separate post-gameweek command.

An explicit `--handoff` is prebuilt reuse, requires `--skip-top100`, and bypasses the
`--projection` build choice. Its capture, season, gameweek and consumer fingerprint are
verified before the mutable alias is touched. The result records `source: prebuilt` and
`new_evidence_applied: false`; it never claims to have reapplied a new Top-100 artifact.
Ordinary built handoffs retain the existing evidence readers and model gates. Alias
publication uses capture-specific retention described in [backup recovery](backup_recovery.md).

Rotation stays opt-in: the default fixture source has not become live intelligence.
Preview league builds write no advice record. Only the explicit publication rebuild writes
the private advice records tied to its generated public bytes.

## Publication and operational acceptance

`--publish` is an external-effect stage. It requires Git/gh and the fresh `origin/develop`
revision to match the run's source revision, renders in an owned worktree under
`.codex-tmp/publications`, and verifies an open PR's exact commit or a no-change result.
Its receipt confirms the PR commit and private record paths. The final merge,
main CI, tag, deploy and canonical-site checks remain the release workflow's responsibility.
A completed weekly run with an open PR is not evidence that the website is live.

If publication fails or is interrupted, its outcome is **uncertain**: automatic resume
cannot repeat the push/PR operation. Inspect the preserved journal, local publication
branch, remote PR/commit and advice records; reconcile them before choosing a new reviewed
run. Do not edit journal statuses into success. No external actions were exercised by the
synthetic acceptance tests.

The generic journal tests exercise real child-process death and lock exclusion, including
a held status read handle during replacement. The weekly tests exercise every real local
service, a resumed Git checkout, immutable capture drift, mutable handoff drift, the old
CLI flags, and the prebuilt/evidence distinction. Clean-wheel acceptance runs the actual
installed runner without `scripts` or repository imports and uses only generated fixtures.
Live shared-mount locking, a real deadline run, backup inclusion of the journal, scheduler
installation and a monitored failed/missed run remain target-environment acceptance work.
Input hashing is conservative and can read substantial archive/capture trees; measure its
cost on the intended storage before choosing a schedule.
