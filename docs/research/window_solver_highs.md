# HiGHS on the member window model

Protocol `docs/window_solver_highs_prereg.md`, issue #984, capture `fpl-live-20261002T104314Z-8b70515b9b31`, commit `6e7e6176a9598a9b45d9fa54f2e85ca6a0e11ca2`. One week of one season with a flat calendar; nothing here claims more.

Run from 2026-10-12T14:58:37+00:00 to 2026-10-12T18:14:45+00:00; head at the end `6e7e6176a9598a9b45d9fa54f2e85ca6a0e11ca2`, runner sha256 `43d0bbf50a5054ec98e31a2e7c36541edf8f80d052cc162f82d8e6e4ca9f0307`.

## Verdicts

- Device: **windows stay on the server**
- Server: **A switch is supported**

## Instances

| Entry | Window | CP-SAT | CP-SAT s | Native matched | Native 1,800 s | Wasm matched | Wasm 1,800 s |
| ---: | ---: | --- | ---: | --- | --- | --- | --- |
| 313686 | 3 | OPTIMAL | 17.6 | proved_optimal, 10.2 s, agrees | proved_optimal, 10.5 s, agrees | proved_optimal, 10.3 s, agrees | proved_optimal, 10.2 s, agrees |
| 313686 | 5 | FEASIBLE | 131.0 | proved_optimal, 105.0 s, differs | proved_optimal, 110.0 s, differs | proved_optimal, 85.5 s, differs | proved_optimal, 76.5 s, differs |
| 2199732 | 3 | OPTIMAL | 27.6 | proved_optimal, 10.6 s, agrees | proved_optimal, 10.4 s, agrees | proved_optimal, 11.5 s, agrees | proved_optimal, 11.7 s, agrees |
| 2199732 | 5 | FEASIBLE | 144.2 | proved_optimal, 38.3 s, differs | proved_optimal, 41.5 s, differs | proved_optimal, 36.2 s, differs | proved_optimal, 35.2 s, differs |
| 2281624 | 3 | OPTIMAL | 24.6 | proved_optimal, 19.2 s, agrees | proved_optimal, 17.0 s, agrees | proved_optimal, 18.3 s, agrees | proved_optimal, 17.6 s, agrees |
| 2281624 | 5 | FEASIBLE | 154.9 | proved_optimal, 57.7 s, differs | proved_optimal, 58.3 s, differs | proved_optimal, 42.2 s, differs | proved_optimal, 40.5 s, differs |
| 3832237 | 3 | OPTIMAL | 28.7 | proved_optimal, 22.4 s, agrees | proved_optimal, 23.5 s, agrees | proved_optimal, 25.9 s, agrees | proved_optimal, 25.2 s, agrees |
| 3832237 | 5 | FEASIBLE | 147.2 | proved_optimal, 60.9 s, agrees | proved_optimal, 61.0 s, agrees | proved_optimal, 55.6 s, agrees | proved_optimal, 53.8 s, agrees |
| 4287206 | 3 | OPTIMAL | 31.0 | proved_optimal, 6.5 s, agrees | proved_optimal, 6.6 s, agrees | proved_optimal, 6.7 s, agrees | proved_optimal, 6.1 s, agrees |
| 4287206 | 5 | FEASIBLE | 123.1 | proved_optimal, 40.4 s, differs | proved_optimal, 40.7 s, differs | proved_optimal, 39.4 s, differs | proved_optimal, 40.8 s, differs |
| 5081114 | 3 | OPTIMAL | 18.9 | proved_optimal, 6.2 s, agrees | proved_optimal, 6.4 s, agrees | proved_optimal, 6.5 s, agrees | proved_optimal, 6.4 s, agrees |
| 5081114 | 5 | FEASIBLE | 146.6 | proved_optimal, 39.9 s, differs | proved_optimal, 39.7 s, differs | proved_optimal, 31.4 s, differs | proved_optimal, 31.8 s, differs |
| 5349883 | 3 | OPTIMAL | 36.6 | proved_optimal, 6.8 s, agrees | proved_optimal, 6.5 s, agrees | proved_optimal, 6.3 s, agrees | proved_optimal, 6.8 s, agrees |
| 5349883 | 5 | OPTIMAL | 112.5 | proved_optimal, 43.9 s, agrees | proved_optimal, 43.4 s, agrees | proved_optimal, 49.2 s, agrees | proved_optimal, 47.9 s, agrees |
| 5662073 | 3 | OPTIMAL | 37.6 | proved_optimal, 19.8 s, agrees | proved_optimal, 21.7 s, agrees | proved_optimal, 18.9 s, agrees | proved_optimal, 19.9 s, agrees |
| 5662073 | 5 | FEASIBLE | 138.3 | proved_optimal, 89.0 s, differs | proved_optimal, 91.2 s, differs | proved_optimal, 82.9 s, differs | proved_optimal, 82.0 s, differs |
| 6654210 | 3 | OPTIMAL | 30.1 | proved_optimal, 7.9 s, agrees | proved_optimal, 7.5 s, agrees | proved_optimal, 7.4 s, agrees | proved_optimal, 7.4 s, agrees |
| 6654210 | 5 | OPTIMAL | 122.5 | proved_optimal, 53.0 s, agrees | proved_optimal, 53.0 s, agrees | proved_optimal, 42.5 s, agrees | proved_optimal, 42.2 s, agrees |
| 6879786 | 3 | OPTIMAL | 29.2 | proved_optimal, 21.4 s, agrees | proved_optimal, 23.0 s, agrees | proved_optimal, 21.1 s, agrees | proved_optimal, 22.4 s, agrees |
| 6879786 | 5 | FEASIBLE | 126.4 | proved_optimal, 66.1 s, differs | proved_optimal, 63.8 s, differs | feasible, 126.4 s, differs | proved_optimal, 133.7 s, differs |
| 6880255 | 3 | OPTIMAL | 18.7 | proved_optimal, 9.3 s, agrees | proved_optimal, 8.9 s, agrees | proved_optimal, 9.0 s, agrees | proved_optimal, 9.4 s, agrees |
| 6880255 | 5 | FEASIBLE | 159.4 | proved_optimal, 45.6 s, differs | proved_optimal, 45.0 s, differs | proved_optimal, 44.9 s, differs | proved_optimal, 44.0 s, differs |
| 7018833 | 3 | OPTIMAL | 38.9 | proved_optimal, 9.8 s, agrees | proved_optimal, 9.9 s, agrees | proved_optimal, 12.6 s, agrees | proved_optimal, 12.7 s, agrees |
| 7018833 | 5 | FEASIBLE | 143.1 | proved_optimal, 45.5 s, differs | proved_optimal, 47.1 s, differs | proved_optimal, 53.2 s, differs | proved_optimal, 51.8 s, differs |
| 7252721 | 3 | OPTIMAL | 18.2 | proved_optimal, 9.7 s, agrees | proved_optimal, 10.0 s, agrees | proved_optimal, 8.6 s, agrees | proved_optimal, 8.5 s, agrees |
| 7252721 | 5 | FEASIBLE | 128.8 | proved_optimal, 42.4 s, differs | proved_optimal, 41.9 s, differs | proved_optimal, 38.6 s, differs | proved_optimal, 39.4 s, differs |
| 8548384 | 3 | OPTIMAL | 20.5 | proved_optimal, 14.0 s, agrees | proved_optimal, 14.2 s, agrees | proved_optimal, 13.6 s, agrees | proved_optimal, 13.4 s, agrees |
| 8548384 | 5 | FEASIBLE | 175.4 | proved_optimal, 62.9 s, differs | proved_optimal, 62.1 s, differs | proved_optimal, 66.2 s, differs | proved_optimal, 65.2 s, differs |
| 8883467 | 3 | OPTIMAL | 32.5 | proved_optimal, 27.9 s, agrees | proved_optimal, 27.8 s, agrees | proved_optimal, 29.5 s, agrees | proved_optimal, 26.5 s, agrees |
| 8883467 | 5 | FEASIBLE | 178.9 | proved_optimal, 133.0 s, differs | proved_optimal, 135.0 s, differs | proved_optimal, 138.6 s, differs | proved_optimal, 139.6 s, differs |

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

## Machine and versions

Windows-11-10.0.26200-SP0, Intel64 Family 6 Model 158 Stepping 10, GenuineIntel, 6 logical cores. OR-Tools 9.15.6755, HiGHS native 1.15.1, wasm 1.15.1 under Node v22.23.3.
