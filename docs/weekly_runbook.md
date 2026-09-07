# Weekly runbook — the league advice loop

One command produces everything the league members' pages need for the coming
gameweek, from the capture to the site pull request:

```bash
python -m scripts.run_week --season 2026-27 --gameweek 4 --league 352490 --workers 8
```

Run it from the checkout you mean to publish from, with that checkout's `src` on
`PYTHONPATH`, after the previous gameweek's picks are public and before the deadline.
`--dry-run` prints the plan and runs nothing.

## What it does, in order

| step | script | what it needs | what it leaves |
| --- | --- | --- | --- |
| capture | `squadopt.platform.fpl_capture.capture` with the entry registry and the league id | `data/entries/registry.json` (`scripts.seed_entry_registry`) | `data/snapshots/fpl-live-<utc>-<hash>/` with bootstrap, fixtures, the last five event-live documents, every member's three documents and the standings page |
| top100 | `scripts.capture_top100_cohort`, `scripts.capture_elite_picks`, `scripts.export_player_evidence` | before the deadline; target gameweek ≥ 2 | `fpl-top100-*` and `fpl-elite-picks-*` snapshots; `artifacts/phase_b/player_evidence_v1_<season>_gw<NN>_top100.{csv,manifest.json}` |
| handoff | `scripts.build_projection_handoff --snapshot-id <capture>` | the capture above | `data/handoffs/<season>-gw<NN>.json` — the Phase C component route by default; `--projection elite` applies the Top-100 uplift on the legacy blend instead |
| league | `scripts.build_league_site --workers N` | the capture and the handoff | `web/public/data/league/**`: `members.json`, `entries/<id>.json`, `advice/<id>/saf-puan/1.json`, `advice/<id>/<strategy>/1.json` (the standings neighbour), `advice/<id>/<strategy>/1/vs-<rival>.json`, `advice/<id>/index.json` |
| site | `scripts.build_site` | the ledger and captures | `web/public/data/**` season views |
| publish | `scripts.publish_gameweek_site --league … --snapshot-id … --in-season-projection … --workers …` (only with `--publish`) | a clean `origin/develop` | a worktree, a commit of `web/public/data`, a push, a pull request; then the printed human steps: merge, release, tag, dispatch |

Every step is skippable by naming its output: `--snapshot-id` reuses a capture,
`--cohort-snapshot` / `--elite-snapshot` reuse the Top-100 captures (the export still
runs), `--skip-top100` leaves the evidence out. The command stops at the first refusal
and prints what refused.

## Timing

- The capture must be open for the requested gameweek; the command reads the deadline
  back from the capture and refuses a mismatch, so a Thursday run for Saturday's
  gameweek is fine and a Sunday run for a Saturday deadline is not.
- The Top-100 captures refuse at or after the deadline, and read the cohort's picks for
  the gameweek that just closed — so they need those picks to be public (after the
  previous deadline) and the coming deadline still open.
- The league tree takes about twenty minutes for fifteen members with `--workers 8`
  (one control plus twenty-eight rival solves per member); one process takes about
  seven times longer. The bytes do not depend on the worker count.

## What is on the site afterwards

For every member: their squad, the pure-points plan, and — against every other member —
the two rival strategies the catalogue computes (`ortak-koru`, `fark-yarat`), each with
captain, vice-captain, eleven, bench order, chip, the expected-points price of the
constraint net of hits, the overlap and the expected gap. The page reads the index to
know what exists; a pair no plan could satisfy is listed with its reason, not hidden.

Windows beyond one week are not computed for members; the page shows them disabled and
says why.

## What stays a person's act

The outward half of publishing — merging the PR, releasing develop to main, the
`site-<season>-gw<NN>-decision` tag, the Pages dispatch — is printed, not performed.
Our own squad's decision (`squadopt gameweek decide`) and settling (`squadopt gameweek
settle`) are separate commands and are not touched here.
