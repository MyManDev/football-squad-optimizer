# Switching the server's window solves to HiGHS: design note

Status: a draft for #1090's last finish condition, written after the record
`window_solver_highs_current.md` read "a switch is supported". It proposes; it changes no
default, and the branch it lives on opens no pull request until the owner says so. The
backend module it describes, `src/squadopt/experiments/highs_window_backend.py`, is wired to
nothing.

## What the record licenses

On the current window model (commit ad7b5c46, after #989 and #1078), native HiGHS 1.15.1 on
one thread proved every GW7 member window CP-SAT proved, at CP-SAT's value and within
CP-SAT's wall time, and at 1,800 s proved all seven five-week windows CP-SAT left FEASIBLE,
four at CP-SAT's incumbent and three above it. The #994 protocol's three server conditions
hold, so a switch may be proposed on #632. One gameweek with a flat calendar; nothing beyond
that is claimed, and no points difference is a certified gain.

## What would change, and where

### The process boundary comes first

OR-Tools ships `libhighs.so.1` inside its wheel, and `highspy` ships another with the same
SONAME. On Linux one process holds one of them: importing `highspy` after OR-Tools fails on a
missing symbol, and importing OR-Tools after `highspy` fails the same way (the measurement
hit both). The server runs CP-SAT in-process for every one-week plan, so HiGHS cannot be a
function call beside it on the Linux hosts the backend runs on. #1083 measured on Windows,
where this does not arise, and the #1090 measurement ran its native solves in a child process
for this reason.

The decision core may not start a process: the contract "The decision core imports no OS or
process module" forbids `subprocess` in `planning/`. So the switch is a port and an adapter:

- `planning/` gets a window solver port, a small protocol with one method that takes the
  window's two models as MPS text plus the primary objective's column coefficients and the
  budget, and returns the rounded column values with a status (`proved_optimal`, `feasible`,
  `no_solution`) and the seconds spent. The planner's `optimize_transfer_plan` keeps its
  CP-SAT path as it is; a new argument, `window_solver`, defaulting to `None`, routes the
  hold probe and the primary solve through the port when one is given, and maps the answer
  back through the fixing step the measurement's exporter calls check 2: every CP-SAT
  variable fixed at its rounded value, CP-SAT confirming feasibility and the primary value,
  the tie-break then solved on CP-SAT from that fixed point as today. A `None` port leaves
  every byte of the current behaviour in place, and a test asserts the one-week and window
  plans of the pinned replay are unchanged with no port.
- The exporter moves out of `scripts/measure_window_solver_highs.py` into the decision core
  (`optimization/milp_export.py`): the MPS writer and reader, check 1 and check 2. The runner
  then imports them from there, so the measurement and the product share one exporter. That
  move is its own pull request under the re-export rule.
- `platform/` gets the adapter: a child-process window solver that runs the backend module
  in a Python process that has not loaded OR-Tools, hands it the MPS text and reads back the
  answer, as `scripts/_highs_native_driver.py` does for the measurement. `platform/` may
  start processes; the adapter is composed into the advice backend where the window solves
  are requested (`application/advice.py` `solve_window_plan` receives the port from its
  composition root, and keeps passing `None` until the switch is turned on).
- The backend module `highs_window_backend.py` moves from `experiments/` to the package the
  adapter imports it from, with its tests.

### The pin

`highspy==1.15.1` is added to `pyproject.toml` (an optional extra, `highs`, so the laboratory
and the tests without it still install) and to `constraints.txt`. The runner's guard already
refuses any other core version; the adapter refuses the same way at start, and the version it
reads is written into every window plan's diagnostics beside the solver name. The project's
`scipy` carries HiGHS 1.12.0 and is not used.

### The import contract

"The CP-SAT solver stays in the decision core" forbids `ortools` outside `optimization`,
`planning`, `scenarios`, `evaluation` and `backtest`. It says nothing about `highspy`, and the
backend module imports `highspy` through `importlib` at call time, which `lint-imports` does
not see. The switch states the rule rather than leaving it to that gap: the contract gains a
sibling, "The HiGHS solver stays in the platform adapter", forbidding `highspy` everywhere
but the adapter's module, and the `importlib` import becomes a plain import there, so the
graph shows it. `tests/architecture/test_layer_contracts.py` gets the corresponding row.

### What stays

CP-SAT keeps the one-week solves, the tie-break, the fixing step, and the window solves of
any league whose composition root passes no port. When the adapter returns `no_solution`
or an error, the window falls back to the CP-SAT path within the same budget, and the
diagnostics say so. No member sees a different plan until the switch is on, and the switch
is on only after the rehearsal below.

## The weekly rehearsal #1090 requires

Before the first publish with HiGHS on, and on the capture of that week:

1. `python -m scripts.measure_window_solver_highs check` on the week's league tree and
   capture, with the record stem of that week: the rebuild gate for every member and check 1
   on every instance.
2. The full menu's window solves twice, once on CP-SAT and once through the adapter, on the
   backend host: every member, both windows, the production budgets. For each instance the
   HiGHS value must agree with CP-SAT's where CP-SAT proves, and must not be below it where
   CP-SAT leaves FEASIBLE, in the record's units of agreement; a disagreement stops the
   switch.
3. The published tree built from the HiGHS plans passes `scripts/check_league_tree.py`, and
   the pinned member plan test of `tests/unit/test_league_views.py` moves only if the plan
   changed for a reason the rehearsal record states.
4. The rehearsal is recorded under `docs/research/` with its own row in the measurements
   index, and the switch pull request names it.

The rehearsal is repeated whenever the window model, the solver pin or the host changes.

## Merge window

The switch touches `planning/`, `application/` and `platform/`, so it merges only in a
window the live-path plan allows (no merge within 24 hours either side of a deadline,
[PR discipline](../architecture/pr_discipline.md)), with the replay checks that document
names, and after the rehearsal above has a record. Astra's agreement is needed for
`planning/` ([ownership](../architecture/ownership.md)).

## Order of pull requests

1. The exporter moves to `optimization/milp_export.py`, re-exported from the runner.
2. The port in `planning/`, the `window_solver=None` argument and the byte-identical test.
3. The adapter in `platform/`, the pin, the contract sibling, the backend module's move.
4. The rehearsal record, then the composition root passes the adapter for league 352490.

Each is one topic and about the size PR discipline asks for; none changes a default before
step 4, and step 4 is the one the live-path plan gates.
