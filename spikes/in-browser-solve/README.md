# Spike: can a member's plan be solved in the member's own browser?

A feasibility experiment, not product code. Nothing here is imported by `src/` or `web/`, and
nothing is deployed. It lives on the branch `experiment/in-browser-solve`.

## The question

The advice backend runs on one machine. Opening the site to any league means either paying
for compute per visitor or moving the per-member solve to the visitor's device. The shared
part of an answer (the projection table) is produced once per capture; the per-member part is
an optimisation over that table. This spike asks whether that optimisation can run in a
browser and return the server's answer.

## What was done

1. `export_instance.py` builds one member's real one-week problem the way the live path does:
   the capture's roster, the projection handoff, the availability rule (`live.recommendation.project`),
   the stated squad sell value through `planning.pricing.spending_power`, and the member
   planning policy. It solves it with the repository's own `optimize_transfer_plan` (OR-Tools
   CP-SAT) and writes the instance with that answer as the reference.
2. `planner.mjs` states the same one-week model as a mixed-integer program in LP text, using
   the server's exact integer objective coefficients, and solves it with
   [HiGHS](https://highs.dev) compiled to WebAssembly (`highs` 1.15.3 on npm). The server's
   deterministic tie-break is reproduced as three small follow-up solves.
3. `run_node.mjs` and `run_league.mjs` run it in Node; `index.html` runs it in a page.

## What was measured

Inputs: capture `fpl-live-20260922T214539Z-364991a4f832`, gameweek 6, model
`phase_c_control_components_v1`, the handoff the published advice was computed from
(fingerprint `223cd1bab0…`), all fifteen members of the league, strategy `saf-puan`, window 1.
Measured on 2026-10-02 on the owner's PC (Intel Core i9-13900HX).

| Check | Result |
| --- | --- |
| Browser-capable solver against the server's solver, same instance | 15 of 15 identical: squad, starting eleven, captain, transfers in and out, integer objective |
| Browser-capable solver against the advice the site published | 15 of 15 identical transfers and captain |
| Seconds per plan in a real browser (Chromium 152, main thread) | min 0.165, median 0.538, max 1.146 |
| Seconds per plan in Node 22 | min 0.18, median 0.587, max 1.19 |
| Seconds per plan for the server's solver on the same instances | min 1.52, median 4.00, max 48.22 |
| Tie-break changed the first answer | 0 of 15 |
| Solver download | `highs.wasm` 3.5 MB, 1.2 MB gzipped; `highs.mjs` 168 KB, 39 KB gzipped |
| Problem size | 667 players, 2,001 binary variables, LP text 109 KiB |

One member's published plan (entry 3832237, five transfers) carries the status `FEASIBLE`: the
server's search was stopped before it proved the plan. The browser-capable solver returned the
same plan and proved it optimal in 0.41 s.

A first export used `data/handoffs/2026-27-gw06.json` and disagreed with the published advice
for three members. That file is a later handoff for the same capture (fingerprint
`fb725c1a4f…`) and prices some players differently, for example one player at 3.59 against
2.03. The two solvers still agreed with each other 15 of 15 on it. The disagreement was the
input, not the solver.

## What was not measured

- **A phone.** Every timing above is from one fast laptop CPU. No phone was tested.
- **Windows of 3 and 5 weeks.** Only the one-week problem was ported. The multi-week model adds
  weeks linked by squad, bank and free-transfer accrual, and the in-horizon sale rule, none of
  which is stated here. The server took 93.0 s and 208.5 s for those on the same PC
  (`docs/architecture/decisions/0009-advice-backend-hosting-options.md`, measured 2026-09-17).
- **Rival strategies, chips, the Top 100 weight, the football model.** Only `saf-puan` with the
  current model.
- **A worker thread.** The page solves on the main thread, which blocks it for the duration.

## What a real feature would still need

- **The projection table in the published tree.** The site publishes each member's fifteen
  with their numbers, not the table for all 667 players. A browser cannot plan without it, so
  the availability-adjusted table would have to be published per capture.
- **A way to read a squad from FPL.** The FPL API sends no `Access-Control-Allow-Origin`
  header (checked on 2026-10-02), so a page on another origin cannot read it. A small
  forwarding endpoint is needed for the visitor's squad, bank and free transfers.
- **One model, two implementations.** The LP here restates rules that live in
  `planning/optimizer.py`. Shipping it means a parity test that fails when the two drift, in
  the way this spike's comparison does by hand.
- **The record.** A plan computed on the visitor's device does not reach the advice record
  unless the page reports it.

## Running it

```bash
# one instance, from the repository root, with the main checkout's data directory
python spikes/in-browser-solve/export_instance.py \
    --capture data/snapshots/<capture> --handoff data/handoffs/by-capture/<capture>/<file>.json \
    --entry-json <published league/entries/<id>.json> --out <dir>/instances/<id>.json

npm install highs@1.15.3            # in <dir>
node run_league.mjs instances advice   # advice: the published league/advice/<id>/saf-puan/1.json
```

For the page, serve a directory holding `index.html`, `planner.mjs`, `highs.mjs`, `highs.wasm`
(both from `node_modules/highs/build`) and `instances_published/` with a `_list.json` naming
the instance files. Instances are not committed: they carry the full projection table.
