# HiGHS on the current member window model: protocol amendment

Status: pre-registered, written before any solve of these instances. It applies the #994
protocol (`docs/window_solver_highs_prereg.md`) to the committed GW7 tree, and it changes no
threshold, no budget, no gate and no verdict condition of that protocol. It declares a
measurement of two solvers on one model, not a model; it changes no planner, default, member
page, capture or publication, and it promotes nothing. Issue: #1090, which follows #984 and
the record of #1083 (`docs/research/window_solver_highs.md`).

## Why this is written

#1083 measured native HiGHS on the window model at commit 6e7e6176, on the GW6 capture
`fpl-live-20261002T104314Z-8b70515b9b31`: wall-matched, native proved all 17 instances
CP-SAT proved, and at 1,800 s it proved all 13 five-week instances CP-SAT left FEASIBLE.
The server verdict was "a switch is supported". Those instances predate #989, which changed
the purchase prices the budget is built from, and #1078, which prices a held sale by one
boolean and drops the lots that cannot change a sale. The model the server solves today is
not the model that was measured, so #1090 asks for a re-measure on the current window model
before any switch is proposed. This document is that re-measure's protocol.

## What has been read

- The #994 protocol and the #1083 record and its row in `docs/measurements_index.md`.
- Issue #1090 and its finish conditions: the 17 + 13 window instances re-exported from the
  current window model on develop, with the capture and the commit named; native HiGHS and
  CP-SAT run under the #994 protocol unchanged, with status, objective and wall time per
  instance; a one-paragraph decision naming the `highspy` pin and the import contract.
- The committed GW7 tree, read by loading the files and not from memory:
  `web/public/data/leagues/352490/device-plan.json` carries capture
  `fpl-live-20261016T060154Z-b1702d00c8cd`, gameweek 7, policy `member_planning_policy_v2`,
  667 players and the rules table; each of the 15 files under
  `web/public/data/leagues/352490/entries/` carries a `device_plan` block of the same capture
  and gameweek; `web/public/data/fixtures.json` carries the same capture, with no unscheduled
  fixture; the published plans under `web/public/data/leagues/352490/advice/<entry>/saf-puan/`
  are all of the same capture: 15 one-week plans, all OPTIMAL; 15 three-week plans, all
  OPTIMAL; 15 five-week plans, 7 OPTIMAL and 8 FEASIBLE. The tree was published by #1123
  (commit d0b20a36).
- The runner `scripts/measure_window_solver_highs.py` as #1083 left it: it hardcodes the GW6
  capture, the old `web/public/data/league/` layout, the record stem `window_solver_highs`
  and both HiGHS builds. The runner's existing tests pass on develop, among them the one that
  holds the runner's window call to the one `solve_window_plan` makes; the tests that read
  the GW6 tree skip, as their docstring says they do once the tree moves on.
- The loader was run once on the GW7 tree before this document was committed, with the
  capture substituted and nothing solved: it reads 15 members at gameweek 7, the published
  rules and coefficients are the ones the code would solve with, and every club has one
  fixture in each of GW7 to GW11. That run saw no solver output and is not a pilot.
- The first start of `measure`, at 12:56Z on 17 October on head 311e3c79, stopped at the
  version guard before any solve: OR-Tools and `highspy` each ship a `libhighs.so.1`, so on
  Linux one process cannot load both, in either order (#1083 ran on Windows, where this
  cannot happen). The native HiGHS side of the runner (the solve functions, the blocked-day
  rule and the version reader, unchanged in their bodies) moved to
  `scripts/_highs_native_driver.py`, which imports `highspy` and the standard library only,
  and the runner runs it as the native child and for the version guard; the runner re-exports
  the moved names. No instance was solved by HiGHS before this change, no threshold changed,
  and the runner commit named below is the one after it.
- The import contract "The CP-SAT solver stays in the decision core" in `pyproject.toml`,
  enforced by `lint-imports` and `tests/architecture/test_layer_contracts.py`: it forbids
  `ortools` outside `optimization`, `planning`, `scenarios`, `evaluation` and `backtest`. A
  production switch to HiGHS would add `highspy` as a solver dependency and would have to
  state, in that contract or beside it, where HiGHS may be imported.

## Instances

- **Members:** the 15 members of league 352490 at GW7, each with a 3-week and a 5-week
  window: 30 instances. The entry ids, read from the tree: 313686, 2199732, 2281624,
  3832237, 4287206, 5081114, 5349883, 5662073, 6654210, 6879786, 6880255, 7018833,
  7252721, 8548384, 8883467. The record states every count it finds: the members, the
  instances, how many CP-SAT proves and leaves FEASIBLE in each window, and how many native
  HiGHS proves in each run.
- **Inputs:** the committed GW7 publication inputs of capture
  `fpl-live-20261016T060154Z-b1702d00c8cd`:
  - `web/public/data/leagues/352490/device-plan.json`;
  - each member's `device_plan` block in `web/public/data/leagues/352490/entries/`;
  - `web/public/data/fixtures.json`.

  The runner reads the capture from the device table and refuses any input file whose
  `source_snapshot_id` differs. No gitignored store is read. 2025-26 is not read.
- **Calendar:** every club has one fixture in each of GW7 to GW11 in the committed calendar,
  so the later weeks' points equal the first week's (`live/horizon.py`), as at GW6. The
  instances are one week of one season with a flat calendar, and the record says so. The
  record computes the calendar from the fixtures file rather than copying this sentence.
- **Model:** `planning/optimizer.py` `optimize_transfer_plan` at the commit named below, with
  `protect_hold=True`, linearization level 2 and the member policy's one transfer a week:
  the path `live/transfers.py` `plan_transfer_horizon` takes from `application/advice.py`
  `solve_window_plan` when the projection model is not `fixture_football_candidate`, as for
  the published member-menu windows. This is the window model after #989 and #1078. The
  planner code is read, never changed. The football windows' route is not measured.
- **The commit measured:** the record's `repository_commit` is the head of branch
  `feat/highs-window-remeasure` at the run, with `working_tree_dirty: false`. The source
  measured is that of the runner commit on that branch; the commit's hash is written into
  this section before the run and after the runner commit, and the head at the run differs
  from it in documents only. Runner commit: `a2ba723025650c8cae4eff46237f9767498c20e0` (the one after the
  native driver change disclosed above; the first named was a85cc75b). On 2026-10-17, after the run, the branch's commits were re-authored under the repository's author identity; the ids in this document are the re-authored ones, each commit kept its tree, message and dates, and nothing else in this document moved.
- **Sell-on fee:** as #994, the runner sets the game's 0.5. The three inputs do not publish
  it, and at the captured prices a lot bought inside the window sells for what was paid.
- **Rebuild gate:** before any timing, the runner rebuilds each member's one-week problem
  from the same inputs and solves it on CP-SAT. The moves, the eleven and the captain must
  equal the published `saf-puan/1.json` for all 15 members, or the run stops with no
  verdict and the record says so. Each window instance is then solved twice on CP-SAT under
  the reference budget; the two must return the same status and primary value, or the run
  stops with no verdict. The reference's three-week values are set beside the published
  ones and every difference is reported; that comparison is not a gate.

## Solvers and budgets

Exactly as #994. Nothing below is new.

- **CP-SAT**, `ortools` as `constraints.txt` pins it (9.15.6755): linearization level 2,
  one worker and the planner's seed (`optimization/optimizer.py` `configure_solver`), 20
  deterministic units per week plus the hold probe's extra unit, and the 1,800 s wall
  ceiling (`WINDOW_DETERMINISTIC_UNITS_PER_WEEK`, `WINDOW_WALL_CEILING_SECONDS`,
  `WINDOW_LINEARIZATION_LEVEL` in `application/advice.py`). This rerun is the reference.
- **HiGHS native**, `highspy` 1.15.1 installed in the runner's environment only, not in
  `constraints.txt` or `pyproject.toml`, one thread. The core version it reports at run time
  is recorded, and the run refuses any other than 1.15.1.
- **Gaps:** `mip_rel_gap` 0 and `mip_abs_gap` 0.5 on the objective's integer scale.
- **Hold floor and start:** HiGHS computes the hold model's optimum itself, inside its timed
  budget, floors the primary at the primary objective of its own hold solution, rounded to
  integers and recomputed exactly, and starts the primary from that whole solution. It takes
  no value and no hint from CP-SAT. When its hold solve returns no solution, its primary runs
  with no floor and no start.
- **Two runs:** each instance runs twice on native HiGHS. One run is limited to the wall time
  CP-SAT spent on that instance (hold probe plus primary solve on the reference run, or
  1,800 s when the wall ceiling stopped CP-SAT); the other has the 1,800 s ceiling. A HiGHS
  primary gets what its own hold solve left of the budget.
- **Time:** `perf_counter` around the solve calls, excluding the model build, the MPS read,
  the floor row, the start and the module load, each recorded apart, as #994 states them.
- **Primary only:** the primary solve is measured, not the tie-break; plans are compared by
  their primary value, never by identity.
- **Machine:** one machine, recorded by the runner (operating system, CPU model, logical
  cores, Python, OR-Tools, `highspy` core version); one solve at a time, nothing else heavy
  on the machine while `measure` runs; the heavy-test slot claimed on #632. The runner's
  rule that no solve runs on 9 or 10 October (UTC) stays in the code as it is; both days
  have passed.

## The device arm

Not measured. The #994 protocol's device verdict was settled by #1083 ("windows stay on the
server": wasm proved only 10 of 15 three-week and 0 of 15 five-week windows within 15 s),
and #1090 does not reopen it. This run makes no wasm solve and loads no Node; the record's
device verdict reads "not measured, carried from docs/research/window_solver_highs.md". The
runner's `--builds native` option skips the wasm version guard and the wasm preflight, and
leaves every other guard in place.

## The exporter and its checks

As #994, unchanged: the runner writes each instance's hold and primary models as MPS, and

1. CP-SAT's solution of each instance, mapped onto the MPS variables, satisfies every row
   within 1e-6 and gives the same primary value;
2. every HiGHS solution, rounded to integers, mapped back and fixed in the CP-SAT model, is
   feasible there and gives the same primary value.

If either check fails on any run, the exporter is wrong and the run stops with no verdict.
Two values agree when they differ by at most 1,000 units (0.001 points). On every instance
CP-SAT proves, the HiGHS optimum at the 1,800 s ceiling must agree with CP-SAT's; a
disagreement makes the verdict "the models disagree", which replaces the server verdict.

The MPS files are evidence under `artifacts/window_solver_highs_current/` (gitignored); each
one's sha256 is in the record.

## What is recorded

`docs/research/window_solver_highs_current.json`, with its markdown twin and a row in
`docs/measurements_index.md`, per ADR 0003. The record names this protocol, #1090, the
capture, the commit, the start and end times, the machine and the versions, and per instance:
CP-SAT's status, primary value, best bound and seconds; for each native run its status
(proved optimal, feasible, no solution or an error), seconds, value, bound, gap and whether
it agrees with CP-SAT. The committed JSON stays under about 250 KB; solver logs and MPS files
stay under `artifacts/`.

## Verdicts

The #994 server conditions, unchanged. "A switch is supported" only if HiGHS native:

1. in the wall-matched run, proves every instance CP-SAT proves, at CP-SAT's value;
2. in the 1,800 s run, proves at least half of the five-week instances CP-SAT's rerun leaves
   FEASIBLE (with none, this condition fails);
3. in the 1,800 s run, on no instance ends with a primary value below CP-SAT's, where below
   means lower by more than the 1,000 units of agreement, and a run that ends with no value
   counts as below.

Otherwise "the server stays on CP-SAT". No solution, an error or a crash counts as not
proved. No run substitutes for another. CP-SAT proves an instance when the reference run's
primary solve is OPTIMAL. The device verdict is carried from #1083 and not re-measured.

The record also states, as #1090 asks, a one-paragraph decision: switch the server's window
solves to HiGHS, naming the `highspy` pin and the change to the import contract "The CP-SAT
solver stays in the decision core", or keep CP-SAT, with the reason. The paragraph follows
the verdict: a switch is proposed only under "a switch is supported", and a disagreement or
a failed condition keeps CP-SAT and names the condition that failed.

## Noise floor

This is a solver measurement: its gate is the three conditions above, and no condition is a
points claim. Where the record reports a difference in points between a HiGHS value and
CP-SAT's incumbent, that difference is a property of one instance on one gameweek and is not
a certified gain; the repository's floor for certifying a points effect, 1.5 points per
gameweek with a 90% interval that excludes zero, is stated here and is not met by any
single-gameweek reading.

## What a result licenses

- "A switch is supported" licenses proposing the move on #632 and the design of a switch:
  the `highspy` pin, the import contract change and the weekly rehearsal #1090 requires
  before the next publish. The switch itself is a separate pull request, merged only in a
  window the live-path plan allows for `planning/`, and nothing here changes a published
  plan.
- "The server stays on CP-SAT" closes #1090 with that answer.
- Neither verdict claims anything beyond one gameweek with a flat calendar.

## Deliberate exclusions

- No wasm run and no device verdict of its own.
- No tie-break, no plan identity, no football window route, no other gameweek, no other
  solver settings, no second run of an instance with other settings.
- No 2025-26 data, no member capture and no gitignored store.
- No change to any threshold, budget, gate or condition of #994.
