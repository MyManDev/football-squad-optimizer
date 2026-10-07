# HiGHS on the member window model: protocol

Status: pre-registered, written before any solve. It declares a measurement of solvers on
one model, not a model. It changes no planner, default, member page, capture or
publication, and it promotes nothing. The delivered scope is this protocol; the exporter
and the runner (`scripts/measure_window_solver_highs.py`) are the next pull request, and
nothing is solved by this document. Issue: #984, part of #978.

## Why this is written

The device answers one-week plans only. The 3 and 5 week windows of the member menu are
solved by the server on CP-SAT, at 20 deterministic units a week with a 1,800 s wall
ceiling, and no one has measured HiGHS on the window model. The measurement decides two
things (#984): whether the device can carry windows, and whether the server's window
solves should move from CP-SAT to HiGHS.

## What has been read

- `docs/measurements_index.md`, `src/squadopt/experiments/` and ADR 0009
  (`docs/architecture/decisions/0009-advice-backend-hosting-options.md`, CP-SAT window
  timings) hold no record of HiGHS or any MILP solver on the window model.
- `docs/member_window_proofs.md` measured CP-SAT's linearization level on the GW5 member
  windows (15 members, 20 units a week): level 2 proved 15 of 15 three-week and 12 of 15
  five-week plans. It is evidence about CP-SAT only.
- `docs/weekly_runbook.md` records a GW6 rehearsal that proved all 300 three-week and 241 of
  300 five-week solves, on an earlier model.
- The published GW6 tree (`web/public/data/league/advice/*/saf-puan/{3,5}.json`, capture
  `fpl-live-20261002T104314Z-8b70515b9b31`) holds 15 three-week plans, all OPTIMAL, and 15
  five-week plans, 2 OPTIMAL and 13 FEASIBLE. Those were solved before #948 changed how paid
  transfers are counted, so they are a reference, not a baseline.
- The in-browser spike (`origin/experiment/in-browser-solve`) solved the one-week model
  only, on capture `fpl-live-20260922T214539Z-364991a4f832`: the npm package `highs` 1.15.3
  matched the server on 15 of 15 members, and the spike lists 3 and 5 week windows as not
  measured.
- After the thresholds below were committed (5d64cf22), on 6 October, one run of the
  runner's `check` command, on its unmerged branch, solved one member, 8883467, on CP-SAT at
  the production budget. Its one-week rebuild matched `saf-puan/1.json`, its 3-week window
  was proved at the published value, and its 5-week window ended FEASIBLE on the
  deterministic budget. It also exported both windows' hold and primary models as MPS, and
  the exporter's first check passed on all four. No threshold changed after it, and no
  HiGHS solve of any instance has run.
- After that check and before any HiGHS solve, on 7 October, the readings the runner
  would otherwise have chosen were written into this protocol: the hold floor, a run's
  time and budget, CP-SAT's model build time, the thread count, the sell-on fee, check
  2's comparison, a run with no solution and CP-SAT's proofs. One adds to what HiGHS
  gets: each HiGHS primary starts from its own hold solution, as the planner starts
  CP-SAT's. None changes a threshold.

## Instances

- **Members:** the 15 members of league 352490 at GW6, each with a 3-week and a 5-week
  window: 30 instances.
- **Inputs:** the committed GW6 publication inputs of capture
  `fpl-live-20261002T104314Z-8b70515b9b31`:
  - `web/public/data/league/device-plan.json`;
  - each member's `device_plan` block in `web/public/data/league/entries/`;
  - `web/public/data/fixtures.json`.

  No gitignored store is read.
- **Calendar:** every club has one fixture in each of GW6 to GW10 in that calendar, so the
  later weeks' points equal the first week's (`live/horizon.py`). The instances are one
  week of one season with a flat calendar, and the record says so.
- **Model:** `planning/optimizer.py` `optimize_transfer_plan` at the runner's merge commit,
  with `protect_hold=True`, linearization level 2 and the member policy's one transfer a
  week. That is the path `live/transfers.py` `plan_transfer_horizon` takes from
  `application/advice.py` `solve_window_plan` when the projection model is not
  `fixture_football_candidate`, as for the published member-menu windows, whose stated
  limits repeat the first week's projection. The football windows' guarded, expected and
  observed route is not measured. The planner code is read, never changed.
- **Sell-on fee:** the three inputs do not publish it, so the runner sets the game's 0.5.
  At the flat captured prices it does not enter the model: each held player's selling
  price is in the member's `device_plan` block, and a player bought inside the window
  sells for what was paid, whatever the fee.
- **Rebuild check:** before any timing, the runner rebuilds each member's one-week problem
  from the same inputs and solves it on CP-SAT. The moves, the eleven and the captain must
  equal the published `saf-puan/1.json` for all 15 members, or the run stops with no
  verdict. Each window instance is then solved twice on CP-SAT under the reference budget;
  the two must return the same status and primary value, or the run stops with no verdict.
  The reference's three-week values are set beside the published ones and every difference
  is reported. That comparison is not a gate, because #948 changed the model since.

## Solvers and budgets

- **CP-SAT**, `ortools` as `constraints.txt` pins it (9.15.6755): linearization level 2,
  one worker and the planner's seed (`optimization/optimizer.py` `configure_solver`), 20
  deterministic units per week with the hold probe's extra unit, and the 1,800 s wall
  ceiling (`WINDOW_DETERMINISTIC_UNITS_PER_WEEK`, `WINDOW_WALL_CEILING_SECONDS`,
  `WINDOW_LINEARIZATION_LEVEL` in `application/advice.py`). This rerun is the reference.
- **HiGHS native**, `highspy` 1.15.3 pinned in the runner's environment only (the project's
  scipy carries HiGHS 1.12.0, which is not used), one thread.
- **HiGHS wasm**, the `highs` 1.15.3 package `web/package.json` pins, under Node 22, one
  thread, loaded as the device's tests load it.
- **Versions:** the HiGHS core version each build reports at run time is recorded, and the
  native and wasm runs count as one version only if the two reports match. Each solve
  also records the thread count its build reports back, or none where the build's API
  reports none.
- **Gaps:** both HiGHS builds use `mip_rel_gap` 0 and `mip_abs_gap` 0.5 on the objective's
  integer scale (below one millionth of a point). On an integer objective this is the same
  proof as the device's own setting of 0.
- **Hold floor and start:** each solver computes the hold model's optimum itself, inside
  its timed budget, and floors the primary at it, as CP-SAT's hold probe does. No solver
  takes another's value or hint.
  - A HiGHS run floors its primary at the primary objective of its own hold solution,
    rounded to integers and recomputed exactly.
  - It also starts its primary from that whole solution, as the planner hints CP-SAT's
    primary with the probe's solution. The hold and primary MPS share their columns, the
    auxiliary ones included.
  - When its hold solve returns no solution, its primary runs with no floor and no start.
- **Two runs per build:** each instance runs twice on each HiGHS build. One run is limited
  to the wall time CP-SAT spent on that instance; the other has the 1,800 s ceiling.
- **Time:** time is `perf_counter` around the solve calls of the hold model and the primary,
  excluding the model build, the MPS read and the module load, each recorded apart. For
  CP-SAT that is the hold probe and the primary solve of the reference run. A CP-SAT run
  stopped by the wall ceiling counts as not proved, and HiGHS then gets 1,800 s.
  - A run's time is its hold solve plus its primary solve. The floor row and the start
    are set before the primary's clock starts, and their time is recorded apart.
  - The wall-matched budget is CP-SAT's hold probe plus primary solve time on the
    reference run. A HiGHS primary gets what its own hold solve left of the budget, and
    a run whose hold solve spends it all has no primary.
  - CP-SAT's model build time is the planner call's wall time less every captured solve,
    the tie-break's included, and less the capture's own model copies. It also holds the
    planner's reading of its answer.
- **Primary only:** the primary solve is measured, not the tie-break. CP-SAT's tie-break
  weights rank sums at magnitudes no floating-point MILP holds exactly, so plans are
  compared by their primary value, never by identity.
- **Machine:** one machine, recorded (CPU, logical cores, operating system, solver
  versions); one solve at a time, with the heavy-test slot claimed on #632. No solve runs on
  9 or 10 October (UTC).

## The exporter and its checks

There is no LP or MPS writer for the CP-SAT model. The runner's exporter writes each
instance's primary model as MPS: the same variables and rows, with the maximum, minimum,
element and enforced constraints linearised using bounds taken from the model itself.
Before any timing counts:

1. CP-SAT's solution of each instance, mapped onto the MPS variables, satisfies every row
   within 1e-6 and gives the same primary value.
2. Every HiGHS solution, rounded to integers, mapped back and fixed in the CP-SAT model, is
   feasible there and gives the same primary value.

If either check fails on any run, the exporter is wrong and the run stops with no verdict.
Check 2 compares CP-SAT's objective at the fixed point with the MPS objective evaluated
exactly at the same rounded point; the objective HiGHS reports is recorded beside them.

Values are compared after rounding a HiGHS solution to integers and recomputing the
primary exactly; two values agree when they differ by at most 1,000 units (0.001 points).
On every instance CP-SAT proves, the HiGHS optimum at the 1,800 s ceiling must agree with
CP-SAT's. A disagreement on either HiGHS build makes the verdict "the models disagree",
which replaces both verdicts below.

The MPS files are evidence under `artifacts/window_solver_highs/` (gitignored); each one's
sha256 is in the record.

## What is recorded

`docs/research/window_solver_highs.json`, with its markdown twin and a row in
`docs/measurements_index.md`, per ADR 0003. It records:

- for each instance, solver and run:
  - the status: proved optimal, feasible, no solution, or an error;
  - the time to proof or to the limit;
  - the primary objective and the best bound;
  - the gap on the integer scale and in points;
  - whether each value agrees with CP-SAT's;
- the rebuild checks, the exporter checks, the machine and the versions.

## Verdicts

The thresholds are fixed here and not changed after the data. No solution, an error or a
crash counts as not proved.

- **Device.** "Device can carry windows on a flat calendar" if HiGHS wasm, in the 1,800 s
  run, proves all 15 three-week instances and at least 14 of the 15 five-week instances,
  each proof within 15 s of wall time on this machine. Otherwise "windows stay on the
  server".
  - A phone is measured afterwards on the same 30 instances with the same wasm build, and
    its model is recorded. The verdict does not wait for it.
- **Server.** "A switch is supported" only if HiGHS native:
  1. in the wall-matched run, proves every instance CP-SAT proves, at CP-SAT's value;
  2. in the 1,800 s run, proves at least half of the five-week instances CP-SAT's rerun
     leaves FEASIBLE (with none, this condition fails);
  3. in the 1,800 s run, on no instance ends with a primary value below CP-SAT's.

  Otherwise "the server stays on CP-SAT".

No run substitutes for another. The conditions read the runs this way:

- CP-SAT proves an instance when the reference run's primary solve is OPTIMAL. The
  five-week instances CP-SAT's rerun leaves FEASIBLE are those whose reference plan is
  FEASIBLE.
- A HiGHS run whose primary returns no solution, or that has no primary, keeps its own
  hold plan's value, as the planner keeps CP-SAT's hold plan, and is not proved.
- In the server's third condition, a value is below CP-SAT's when it is lower by more
  than the 1,000 units of agreement. A HiGHS native run that ends with no value, through
  no solution, an error or a crash, counts as below.

## What a result licenses

- "Device can carry windows on a flat calendar" licenses #984's step 2, the multi-week
  device model, which must equal the server's window plans on the rehearsal set. No device
  window is published until a gameweek with a blank or a double has been measured under
  the same threshold.
- "A switch is supported" licenses proposing the move to HiGHS on #632. `planning/**` is
  Astra's lane, and nothing moves without that agreement.
- Neither verdict claims anything beyond one gameweek with a flat calendar, and neither
  changes a published plan.

## Deliberate exclusions

- No tie-break is measured or compared, and no plan identity. The planner still solves its
  tie-break inside a CP-SAT run whose primary it proves with deterministic budget left;
  its status is recorded, and its time counts in no run's time.
- No football window route.
- No other gameweek.
- No other solver settings: no CP-SAT worker count other than one, and no HiGHS presolve
  or heuristic tuning.
- No second run of an instance with other settings.
- No 2025-26 data, no member capture and no gitignored store.
