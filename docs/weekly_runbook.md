# Weekly runbook — the league advice loop

One command produces everything the league members' pages need for the coming
gameweek, from the capture to the site pull request, and — when asked — decides our
own squad on the way:

```bash
python -m squadopt.platform.weekly_operations --season 2026-27 --gameweek 4 --league 352490 --workers 8 --decide --run-id 2026-27-gw04-decision
```

Run the installed package from the clean checkout you mean to publish from (or pass
`--workspace`). The legacy `python -m scripts.run_week` flags still delegate to this runner.
Start after the previous gameweek's picks are public and inside the lead-time window below — "before the deadline" is a floor, not the policy.
`--dry-run` prints the plan and runs nothing. Without `--decide` the ledger is not
touched and the loop is the members' loop alone.

The preview now defaults to `data/runtime/weekly/<run-id>/preview`, rather than tracked
`web/public`. `--out` still selects another destination. A source-controlled destination can
make the checkout dirty and must be reconciled before a resume; the default avoids that.
Every stage records its inputs, exit/result and output hashes. Reuse the same arguments and
`--run-id` with `--resume`; changed inputs or outputs refuse. `--status --run-id <id>` verifies
results, and `--expected-at <UTC instant>` additionally evaluates missed completion. See
[weekly operations](architecture/weekly_operations.md) for recovery and scheduling limits.

## What it does, in order

| step | service / compatibility command | what it needs | what it leaves |
| --- | --- | --- | --- |
| top100 | `scripts.capture_top100_cohort`, `scripts.capture_elite_picks`, `scripts.export_player_evidence` | before the deadline; target gameweek ≥ 2 | `fpl-top100-*` and `fpl-elite-picks-*` snapshots; `artifacts/phase_b/player_evidence_v1_<season>_gw<NN>_top100.{csv,manifest.json}` |
| capture | `squadopt.platform.fpl_capture.capture` with the entry registry and the league id | `data/entries/registry.json` (`scripts.seed_entry_registry`) | `data/snapshots/fpl-live-<utc>-<hash>/` with bootstrap, fixtures, the last five event-live documents, every member's three documents and the standings page |
| settled outcomes | `application.settled_outcomes.export_settled_outcomes` | stored captures no newer than the selected capture; an earlier week with both pre-deadline and finished/checked captures | immutable table/manifest pairs under `artifacts/rotation`, plus per-run reports; unavailable pairs are stated, never filled with zero outcomes |
| rotation | `scripts.export_rotation_evidence --snapshot <capture> --deadline-utc …` (only with `--rotation`) | the capture above, and a club-news source — **today that source is the committed synthetic fixture** | `artifacts/rotation/rotation_evidence_v2_<season>_gw<NN>_<capture hash>.{csv,manifest.json}` — one row per roster player in that capture, one categorical claim field, and the citation carried as a document digest plus a byte span rather than as text. Written exactly once per capture; a pair already on disk for it is reused rather than remade |
| handoff | `scripts.build_projection_handoff --snapshot-id <capture> --evidence-table … --evidence-manifest …` | the capture above and the evidence | `data/handoffs/<season>-gw<NN>.json` — the Phase C component projection with the bounded Top-100 uplift on top (`phase-c-component-elite-top100-v1`); `--projection component-only` leaves the uplift out; without settled live history the producer falls back to the legacy blend and says so |
| decide | `squadopt.application.commands.decide`, in-process (only with `--decide`; `--chip` as `squadopt gameweek decide` takes it) | the capture and the handoff, each verified at its own stage; a ledger that holds the previous gameweek, and — with `--chip` — an open, unspent chip window, both checked **before** the first capture, so a week the ledger cannot start refuses without spending one. The mode is derived, never asserted: `live` only when this run took the capture and the clock is still before its deadline; a reused `--snapshot-id`, or a run past the deadline, is recorded `replay`. A gameweek the ledger already holds is skipped rather than refused, so a run that died after the decision can rebuild the rest of the week | `data/ledger/<season>/gw<NN>/` — decision, projections, report, manifest; the report is printed |
| league | `scripts.build_league_site --workers N` | the capture and the handoff | `<preview>/data/league/**`: `members.json`, `entries/<id>.json`, `advice/<id>/saf-puan/1.json`, `advice/<id>/saf-puan/3.json` and `5.json` (the week-1 projection repeated over the calendar, published with its stated limits), `advice/<id>/<strategy>/1.json` (the standings neighbour), `advice/<id>/<strategy>/1/vs-<rival>.json`, `advice/<id>/index.json` (`windows` names what solved per strategy; a window that did not is in `unavailable` with its reason). A local preview: these bytes are never committed, so this step writes no advice record (`--no-advice-record`) and the publish step's rebuild records the bytes that actually ship |
| site | `scripts.build_site` | the ledger and captures | `<preview>/data/**` season views (they read the ledger, so after the decision) |
| scoreboard | `scripts.build_scoreboard --cohort-snapshot <fpl-top100 id> --elite-snapshot <fpl-elite-picks id>` | the capture, the registry, the ledger, and the Top-100 captures when they were taken or reused | `<preview>/data/league/scoreboard.json` — per played gameweek: the game's average and highest, every member's gross week, hit cost and net, our ledger row with its mode and its scoring basis, the Top-100 mean for the cohort capture's own week with the basis it is on; `null` wherever a file on disk does not say |
| publish | `scripts.publish_gameweek_site --league … --snapshot-id … --in-season-projection … --cohort-snapshot … --elite-snapshot … --workers …` (only with `--publish`) | a clean `origin/develop` | an owned `.codex-tmp/publications/gw<NN>-decision` worktree, a commit of `web/public/data` (league tree and scoreboard rebuilt there from the same capture), a push, a pull request; then the printed human steps: merge, release, tag, dispatch. The rebuild also writes this checkout's `data/advice_records/<season>/gw<NN>/entry-<id>/<snapshot id>/` — the immutable record of what each member was told, digests included, so the week can be reviewed after the site has been overwritten. One record per capture: publishing a week twice (mid-week, then again before the deadline from a fresher capture) records both, and the review page reads the last capture that preceded the deadline. What is **refused** is rebuilding *one* capture into different bytes — the capture is the whole input, so that difference is our own code's — with the differing fields named; if the deadline will not wait, `--no-advice-record` publishes without recording and leaves the first record and the difference to be reconciled afterwards |

Existing captures can be named explicitly: `--cohort-snapshot` / `--elite-snapshot`
reuse the Top-100 captures. For an optional final-24-hour information audit, take a
second capture and run `squadopt.platform.capture_measurement` as described in
[capture measurement](operations/capture_measurement.md); the output counts changed
fields and does not establish a decision gain. Historical GW1–GW4 availability was
lost, so that gain remains unmeasured until new paired captures accumulate.

The Top-100 options
reuse the Top-100 captures (an export already on disk for that picks capture is reused,
and the named cohort capture also feeds the scoreboard), `--snapshot-id` reuses a live
capture — then the Top-100 captures must be reused or skipped too, because the
projection refuses evidence captured after the decision capture — and `--skip-top100`
leaves the evidence out (the scoreboard's Top-100 column is then `null`). The command
stops at the first refusal and records what refused. An explicit `--handoff` reuses a verified
prebuilt projection for this exact capture and week; it requires `--skip-top100`, bypasses
`--projection` build selection, and records that no new evidence was applied.

**`rotation` is the one step that works the other way round: it is off unless `--rotation`
asks for it.** That is deliberate and it is about honesty of the record, not convenience.
The only club-news source wired up today is the committed *synthetic* fixture under
`data/sample/`, so a step that ran by default would write fixture-derived claims into a real
week's artifact — an artifact the member-facing card is meant to read. When a real source is
connected the default can be turned over; until then the flag is the consent. Reusing a live
capture with `--rotation` requires that capture's export **already on disk**, refused before
anything is spent: the pair records when it was generated, the claim chain has to be frozen
before the decision capture, and re-exporting now for a capture already taken stamps it
afterwards however promptly it is done.

The elite-picks capture travels with the cohort capture into the scoreboard, and it is
what lets the Top-100 column be **net**: the Overall standings publish `event_total`
gross of the week's transfer cost, so a mean over the standings alone is not on the
members' basis. The picks documents carry each member's own `entry_history`, so when the
capture covers all hundred of that week the mean is `points - event_transfers_cost` per
member. Without one — `--skip-top100`, or a picks capture that missed a member — the mean
is published **gross**, labelled gross, and the card says it does not compare with the
net columns beside it.

## Timing

- **Take the capture two to three hours before the deadline, not the night before.**
  The capture must be open for the requested gameweek — the command reads the deadline
  back from it and refuses a mismatch — but "open" is a floor, not the policy. The week
  is decided from that one capture and availability is applied once from it, so a note
  the platform adds afterwards is not late, it is absent, and no later step recovers it.
  Running a day or more ahead leaves that whole span unseen.
- The size of what is unseen is measured, not argued.
  `python -m scripts.measure_capture_lead_time` reads the stored captures and writes
  `docs/capture_lead_time.json`: per gameweek, each capture's lead time and how many of
  the source's own notes were stamped inside the window between the earliest and the
  latest capture. Take a second capture inside the window and the week's own numbers
  appear there. A gameweek captured once reports **not measured**, never zero.
- Two to three hours, rather than as late as possible, for one reason: everything the
  week needs has to fit **before** the deadline, in order — capture, handoff, decide,
  and the league tree's twenty minutes for fifteen members. A capture at thirty minutes
  leaves no room for a step that fails and has to be run again.
- Do not read the feed's own `news` as cover for capturing early. The rotation-lane
  brief (2026-09-08) measured its items on the 2026-09-07 capture at a median of 22.9
  days behind it, with 3 of 71 added since the previous deadline; no artifact in this
  repository carries that measurement yet, so it is cited here rather than claimed.
- **`--rotation` runs after the capture, and the club documents must have been fetched
  before it.** The export reads the capture's own roster and its own deadline, which is why
  it cannot run earlier; and it refuses a week whose club documents carry a fetch instant at
  or after the capture, because words fetched after a capture could have been chosen by
  looking at it first. So the club-news fetch belongs in the same window as everything else,
  ahead of the capture rather than after it. The model call, when there is one, is bound by
  the same rule and more tightly — that is a step of its own and does not exist yet.
- The Top-100 captures refuse at or after the deadline, and read the cohort's picks for
  the gameweek that just closed — so they need those picks to be public (after the
  previous deadline) and the coming deadline still open.
- The league tree takes about twenty minutes for fifteen members with `--workers 8`
  (one control plus twenty-eight rival solves per member); one process takes about
  seven times longer. The bytes do not depend on the worker count.
- `--decide` needs the ledger to hold the previous gameweek. A week that was skipped
  must be recorded first (below); the pre-flight says so before anything is captured.

## Our own squad: catching the ledger up, then deciding, then settling

Our squad is a paper ledger, not an FPL entry: it is decided into `data/ledger/` and
scored from a later capture. `held_squad_from_ledger` wants exactly the previous
gameweek's decision, so a gameweek the loop did not run for has to be recorded from a
capture taken before its deadline — `squadopt gameweek decide` with an explicit
`--snapshot-id` stamps such an entry `replay`, and the season ledger's Mode column shows
it. As of 2026-09-07 the ledger holds GW1 only, so GW2 and GW3 come first, each from the
capture its handoff was built from (`source_snapshot_id` in `data/handoffs/`):

```bash
# GW2: handoff 2026-27-gw02.json was built from this capture (GW2 open, GW1 scored)
squadopt gameweek decide --season 2026-27 --gameweek 2 \
  --snapshot-id fpl-live-20260826T083133Z-d45f1bea8b68 \
  --in-season-projection data/handoffs/2026-27-gw02.json
# GW2 settles from a capture in which GW2 is finished and checked
squadopt gameweek settle --season 2026-27 --gameweek 2 \
  --snapshot-id fpl-live-20260903T105145Z-8eb7745fbe28

# GW3: handoff 2026-27-gw03.json was built from this capture (GW3 open, GW2 scored)
squadopt gameweek decide --season 2026-27 --gameweek 3 \
  --snapshot-id fpl-live-20260903T105145Z-8eb7745fbe28 \
  --in-season-projection data/handoffs/2026-27-gw03.json
# GW3 settles from the GW4 capture, in which GW3 is finished and checked
squadopt gameweek settle --season 2026-27 --gameweek 3 \
  --snapshot-id fpl-live-20260907T131414Z-db9314d00961
```

Each decide verifies the handoff against the capture and the model version against the
promoted in-season controls before anything is written; a refusal leaves the ledger as it
was. Then the weekly command with `--decide` records GW4 from the capture it takes, and
stamps it `live` only if it took that capture itself and the deadline has not passed —
a catch-up run after the deadline, from the same pre-deadline capture, is recorded
`replay`, because it was not decided before the deadline whatever it was decided from. After the gameweek, settle it from a capture in which it is finished and checked
(the Monday capture, or a fresh one):

```bash
squadopt gameweek settle --season 2026-27 --gameweek 4 --snapshot-id <fpl-live id>
python -m scripts.run_week ... --snapshot-id <that id> --skip-top100     # or --publish
```

Settling regenerates `docs/season_ledger_2026-27.md` and the scoreboard's row of ours
fills in on the next site build. Settle stays a separate command on purpose: it needs a
capture the decision run cannot have taken.

## What is on the site afterwards

For every member: their squad, the pure-points plan, and — against every other member —
the two rival strategies the catalogue computes (`ortak-koru`, `fark-yarat`), each with
captain, vice-captain, eleven, bench order, chip, the expected-points price of the
constraint net of hits, the overlap and the expected gap. The page reads the index to
know what exists; a pair no plan could satisfy is listed with its reason, not hidden.

The `/league` page carries the weekly scoreboard: per finished gameweek, our paper
ledger's figure (labelled with its mode), the league members' mean net, the Top-100 mean
with the basis it is on, the game's average and its highest score, with a cumulative row
that names the weeks each figure covers. A member's net is their gross week minus the
transfer cost, read from their own history, and the Top-100 mean is netted the same way
when the week's picks capture covers the cohort.

Our own figure is not FPL's net and the card says so in both languages: it is the eleven
the decision named, scored as named. The game's automatic substitutions are not applied,
and the frozen decision names no vice-captain, so a captain who did not play is not
recovered. Neither correction is computable from what the ledger holds — the decision
records its bench as a set, not in the order autosubs walk it — and both would only add
points, so the row reads low against a real entry. In GW1 the named starters Watkins and
Mukiele both played nought minutes while the bench held two defenders who played ninety
and scored 4 and 1, so the published 26 is roughly five short of what that squad would
have scored as an FPL entry.

A gameweek that has finished but has not been data-checked in the capture is marked
provisional: bonus points land fixture by fixture, so its scores can still move.

Windows beyond one week are not computed for members; the page shows them disabled and
says why.

## What stays a person's act

The outward half of publishing — merging the PR, releasing develop to main, the
`site-<season>-gw<NN>-decision` tag, the Pages dispatch — is printed, not performed.
Settling our squad (`squadopt gameweek settle`) and the replayed catch-up decisions above
are separate commands run by a person; the weekly command decides only when `--decide`
asks it to, and never settles.
