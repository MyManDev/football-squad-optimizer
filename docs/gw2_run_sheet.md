# GW2 run sheet — Friday 2026-08-28

The first *in-season* decision: unlike GW1, the projection arrives as a produced handoff,
and the site publishes **before** the deadline. `opening_week_runbook.md` remains the
authority on principles; `deployment_runbook.md` owns the weekly publish rhythm; this sheet
is the order of commands for this specific Friday. Deadline **17:30Z**. The capture window
opens at T−3h (14:30Z); 15:30Z below is the chosen time inside it, not its edge.

What is new this week, and why the order changed:

- **A producer step sits between capture and decide.** Mid-season gameweeks are refused
  without an in-season projection handoff (`live/recommendation.py`), and the handoff must
  be built **from the same capture the decision runs on** — the decide compares season,
  gameweek and capture id and refuses a mismatch. So: capture first, then produce, then
  decide. A capture-mismatch refusal at decide has exactly one meaning: the producer step
  was skipped or ran against an older capture. Re-run the producer with the fresh capture;
  its output overwrites any stale file at the same path.
- **The decision view ships before the deadline.** GW1's after-the-deadline publish was a
  one-week exception; from GW2 on, `deployment_runbook.md` is authoritative — the decision
  view goes to production before 17:30Z, and the settled view follows after results.

## Before Friday (owner prep, not deadline work)

- #181 (the `in-season-carry-over-v1` pin and the omitted-player refusal) and #183 (the
  producer script) are merged; the Monday rehearsal ran the producer against a real
  post-settle capture and the round-trip verified.
- A deliberate develop-to-main release with green main-push CI exists, and the immutable
  annotated execution tag `run-2026-27-gw02` is on that exact main SHA. Same rules as GW1:
  no existing tag moves, and the tag is created only after the main-push CI is green.

## 15:30Z — capture, then produce

```console
git switch --detach run-2026-27-gw02   # fallback: git switch develop && git pull --ff-only
git rev-parse HEAD                      # record this; it is the tree the tick ran from
python -m pip install -e ".[api,dev]"   # what CI installs; add -c constraints.txt on 3.13
python -m pytest -q                     # green, or stop
python -m scripts.capture_deadline_snapshot
python -m scripts.build_projection_handoff --snapshot-id <the id just printed>
```

The producer prints its identity line, the played-history coverage, the declared
carry-over/in-season weights, and writes `data/handoffs/2026-27-gw02.json`, reading it
straight back and comparing fingerprints. Read the coverage block: every roster player must
be priced by one of the ladder's rungs (in-season blend / carry-over / opening-price
prior), and the counts say how many came from each — a surprising shift between rungs is
worth a pause before deciding.

## ~15:45Z — decide, and the human read

```console
squadopt gameweek decide
```

- Exit 1 = nothing recorded; read the failure. A capture/gameweek mismatch means the
  producer step was skipped — re-run it and decide again. Never edit checks on Friday.
- The report's projection source line must say `in_season_handoff` with model version
  `in-season-carry-over-v1`; `operational_control` on a mid-season week is stop-everything.
- Read the transfer block the way GW1's prior-dependence was read: the planner's suggested
  moves, the hit arithmetic, and the free-transfer count it believed. This is the first
  week transfers exist — a nonsensical count here is an input problem, not a solver one.

## Before 17:30Z — publish the decision view

```console
git fetch origin
git worktree add -b feature/gw02-decision-site ../squadopt-gw02-decision origin/develop
python -m scripts.build_site --out ../squadopt-gw02-decision/web/public
python -m scripts.recommend_current_squad --snapshot-id <id> --output artifacts/live/gw2_replay.txt
git -C ../squadopt-gw02-decision add web/public/data
git -C ../squadopt-gw02-decision commit -m "site: publish the gw02 decision view"
```

Replay must reproduce the report from the recorded execution commit — one spot-check.
Push the branch, PR to develop, release develop→main (green CI), create the annotated tag
`site-2026-27-gw02-decision`, and dispatch the trusted Pages workflow with it. The budget's
two reserved production slots exist for exactly this dispatch. Raw `data/ledger` and
`data/handoffs` stay local, as always.

## After the gameweek (Monday-ish) — settle and the settled view

Same shape as GW1's settle: capture after the last fixture, `squadopt gameweek settle
--gameweek 2`, rebuild the site in a fresh worktree branch, release, tag
`site-2026-27-gw02-settled`, dispatch. The settled view now carries each player's realized
points and the captain multiplier (#184), so the page shows projection against outcome
without recomputation.

## Do-not list for Friday

- Do not change code from the live checkout; the tree is the release.
- Do not decide without the producer step; a mismatch refusal is the system telling you it
  was skipped.
- Do not read `--risk-residuals` unless the risk inputs were prepared and reviewed before
  Friday; `not_requested` remains the honest state until then.
- Windowed, crowd-relative claims stay diagnostics: the site ships price tags, not
  probabilities (`windowed_rank_note.md`).
