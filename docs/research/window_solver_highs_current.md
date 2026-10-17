# HiGHS on the member window model at GW7

Protocol `docs/research/window_solver_highs_current_prereg.md`, issue #1090, capture `fpl-live-20261016T060154Z-b1702d00c8cd`, commit `6163d4e83db60d2152808f354e251f899b402055`. One week of one season with a flat calendar; nothing here claims more.

Run from 2026-10-17T13:17:40+00:00 to 2026-10-17T15:06:41+00:00; head at the end `6163d4e83db60d2152808f354e251f899b402055`, runner sha256 `1491abc2c0ab348b1653836189dc25c7af949be01104b2a876fccb95c3e9da5a`. The branch's commits were re-authored on 2026-10-17 under the repository's author identity after the run; each kept its tree, message and dates, so the commit named here is the code that ran under a new id (its tree is `f446538545f936f9a50372b34056dccb9e3ecc48`).

## Verdicts

- Server: **A switch is supported**
- Device: **not measured, carried from docs/research/window_solver_highs.md**

## Instances

| Entry | Window | CP-SAT | CP-SAT s | Native matched | Native 1,800 s |
| ---: | ---: | --- | ---: | --- | --- |
| 313686 | 3 | OPTIMAL | 16.5 | proved_optimal, 8.7 s, agrees | proved_optimal, 8.3 s, agrees |
| 313686 | 5 | FEASIBLE | 96.4 | proved_optimal, 54.1 s, agrees | proved_optimal, 53.8 s, agrees |
| 2199732 | 3 | OPTIMAL | 23.2 | proved_optimal, 11.6 s, agrees | proved_optimal, 12.0 s, agrees |
| 2199732 | 5 | FEASIBLE | 130.4 | feasible, 130.4 s, differs | proved_optimal, 152.3 s, differs |
| 2281624 | 3 | OPTIMAL | 19.4 | proved_optimal, 4.1 s, agrees | proved_optimal, 4.6 s, agrees |
| 2281624 | 5 | FEASIBLE | 122.0 | proved_optimal, 38.5 s, agrees | proved_optimal, 39.5 s, agrees |
| 3832237 | 3 | OPTIMAL | 20.2 | proved_optimal, 10.8 s, agrees | proved_optimal, 11.1 s, agrees |
| 3832237 | 5 | FEASIBLE | 111.9 | proved_optimal, 41.3 s, agrees | proved_optimal, 39.8 s, agrees |
| 4287206 | 3 | OPTIMAL | 7.1 | proved_optimal, 2.2 s, agrees | proved_optimal, 2.3 s, agrees |
| 4287206 | 5 | OPTIMAL | 50.3 | proved_optimal, 15.0 s, agrees | proved_optimal, 16.2 s, agrees |
| 5081114 | 3 | OPTIMAL | 12.4 | proved_optimal, 4.3 s, agrees | proved_optimal, 4.5 s, agrees |
| 5081114 | 5 | FEASIBLE | 103.1 | proved_optimal, 31.9 s, differs | proved_optimal, 32.6 s, differs |
| 5349883 | 3 | OPTIMAL | 10.4 | proved_optimal, 2.9 s, agrees | proved_optimal, 2.6 s, agrees |
| 5349883 | 5 | OPTIMAL | 78.3 | proved_optimal, 20.5 s, agrees | proved_optimal, 20.0 s, agrees |
| 5662073 | 3 | OPTIMAL | 20.7 | proved_optimal, 19.7 s, agrees | proved_optimal, 19.4 s, agrees |
| 5662073 | 5 | OPTIMAL | 103.5 | proved_optimal, 101.0 s, agrees | proved_optimal, 98.4 s, agrees |
| 6654210 | 3 | OPTIMAL | 20.6 | proved_optimal, 4.6 s, agrees | proved_optimal, 4.5 s, agrees |
| 6654210 | 5 | OPTIMAL | 102.5 | proved_optimal, 43.4 s, agrees | proved_optimal, 42.3 s, agrees |
| 6879786 | 3 | OPTIMAL | 33.2 | proved_optimal, 17.0 s, agrees | proved_optimal, 18.8 s, agrees |
| 6879786 | 5 | FEASIBLE | 96.8 | proved_optimal, 43.1 s, differs | proved_optimal, 43.1 s, differs |
| 6880255 | 3 | OPTIMAL | 10.4 | proved_optimal, 1.6 s, agrees | proved_optimal, 1.7 s, agrees |
| 6880255 | 5 | OPTIMAL | 33.1 | proved_optimal, 20.8 s, agrees | proved_optimal, 19.1 s, agrees |
| 7018833 | 3 | OPTIMAL | 12.2 | proved_optimal, 3.3 s, agrees | proved_optimal, 3.3 s, agrees |
| 7018833 | 5 | OPTIMAL | 116.6 | proved_optimal, 29.6 s, agrees | proved_optimal, 30.3 s, agrees |
| 7252721 | 3 | OPTIMAL | 17.7 | proved_optimal, 9.4 s, agrees | proved_optimal, 9.7 s, agrees |
| 7252721 | 5 | FEASIBLE | 90.0 | proved_optimal, 49.8 s, differs | proved_optimal, 50.4 s, differs |
| 8548384 | 3 | OPTIMAL | 22.6 | proved_optimal, 4.1 s, agrees | proved_optimal, 5.0 s, agrees |
| 8548384 | 5 | OPTIMAL | 78.8 | proved_optimal, 36.6 s, agrees | proved_optimal, 35.7 s, agrees |
| 8883467 | 3 | OPTIMAL | 14.6 | proved_optimal, 7.5 s, agrees | proved_optimal, 7.3 s, agrees |
| 8883467 | 5 | OPTIMAL | 99.1 | proved_optimal, 42.9 s, agrees | proved_optimal, 39.7 s, agrees |

## Counts

- Members 15, instances 30.
- 3-week: 15 instances; CP-SAT proves 15 and leaves 0 FEASIBLE; proved by native wall matched 15, native ceiling 15.
- 5-week: 15 instances; CP-SAT proves 8 and leaves 7 FEASIBLE; proved by native wall matched 14, native ceiling 15.

## Readings

- The primary MPS omits CP-SAT's hold floor. Each HiGHS run floors its own primary at the value of its own hold solution, rounded to integers and recomputed exactly, and starts the primary from that rounded solution, when its hold solve returned a solution; without one its primary runs with no floor and no start.
- A run's time is its hold solve plus its primary solve. The wall-matched budget is CP-SAT's hold probe plus primary solve time on the reference run, and a HiGHS primary gets what its own hold solve left of the budget. The floor row and the start are set before the primary's clock starts, and their time is recorded apart.
- A HiGHS run whose primary returns no solution, or that has no primary, keeps its own hold plan as its value, as the planner keeps CP-SAT's hold plan, and is not proved.
- CP-SAT proves an instance when the reference run's primary solve is OPTIMAL. The five-week instances CP-SAT's rerun leaves FEASIBLE are those whose reference plan is FEASIBLE.
- In the server's third condition, a value is below CP-SAT's when it is lower by more than the 1,000 units of agreement. A HiGHS native run that ends with no value, through no solution, an error or a crash, counts as below.
- Check 2 compares CP-SAT's objective at the fixed point with the MPS objective evaluated exactly at the same rounded point; the objective HiGHS reports is recorded beside them.
- The sell-on fee is the game's 0.5. The three input documents do not publish it; at the flat captured prices it does not enter the model.
- CP-SAT's primary starts from its hold solution: the planner floors the primary at the hold value and also hints every variable with the probe's solution (planning/optimizer.py). Each HiGHS primary gets both from its own hold solution: the floor row and the rounded solution as a start (setSolution). Neither build takes CP-SAT's.
- CP-SAT's model build time is the planner call's wall time less every captured solve, the tie-break's included, and less the capture's own model copies; it also holds the planner's reading of its answer. The tie-break's time counts in no run's time.
- Both HiGHS builds run on one thread: the native build is set to one, and the wasm build is single-threaded and refuses a thread option. Each solve records the thread count its build reports back, or none where the build's API reports none.
- The wasm build was not run: the device verdict was settled by #1083 and is carried from docs/research/window_solver_highs.md, not re-measured.

## Machine and versions

Linux-6.18.44-fc-v139-x86_64-with-glibc2.39, Intel(R) Xeon(R) Processor @ 2.10GHz, 4 logical cores, Python 3.13.16. OR-Tools 9.15.6755, HiGHS native 1.15.1, no wasm run.

## Decision

Switch the server's three- and five-week window solves to native HiGHS, as a proposal on #632 and not in this pull request. On the current window model (commit 6163d4e8) the three conditions hold: wall-matched, native proves every instance CP-SAT proves at CP-SAT's value; at 1,800 s it proves at least half of the 7 five-week instances CP-SAT leaves FEASIBLE; and on no instance does it end below CP-SAT's value. The switch is a separate pull request: it pins `highspy==1.15.1` in `constraints.txt` and `pyproject.toml`, it changes the import contract "The CP-SAT solver stays in the decision core" in `pyproject.toml` so that the one module in `planning/` that drives HiGHS is where `highspy` is imported and `ortools` stays forbidden outside the decision core, it keeps CP-SAT for the one-week solves and as the fallback when HiGHS returns no solution, and it is merged only in a window the live-path plan allows for `planning/`, after a full weekly rehearsal before the next publish (#1090).
