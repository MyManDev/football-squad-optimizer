# Branching and Protection

Where work lands, what must pass before it lands, and what `main` is for.

## The trunk

**`develop` is the trunk. `main` is release history.**

Every pull request targets `develop`. `main` advances only on a deliberate release merge from
`develop`. The first release merge happened in #130, tagged `v2026-27.gw01`, so `main`
carries the opening-season pointer instead of an empty tree. The live static site is the
latest successful immutable `site-...` deployment tag, so production may deliberately lag
`main`; the deployment Actions summary answers "what is running", while `main` answers
"what is releasable". GitHub's default branch is `develop`, which is where work lands.

## Protection

Both branches are protected. Current required checks on `develop` are the two Python gate
contexts, `gates (py3.11)` and `gates (py3.13)`, with strict up-to-date branches. Each context
runs the five Python gates below. The web job also runs in CI but is not currently a protected
required context.

The required approving review count is zero, matching the team's check-then-squash workflow.
Force-push and branch deletion are disabled. `main` uses the same two required contexts and
normal changes reach it through a deliberate release pull request from `develop`.

`main` additionally allows no direct pushes at all: it moves by release merge only.

`delete_branch_on_merge` is deliberately false. Feature branches are retained after squash
merge under the current team policy; do not prune them merely because their pull request
closed.

## The gates

Five exist today. The first four are also documented in `../../README.md` under Quality checks,
`../handoff_acceptance_checklist.md:36` item 16, and `../recalibration_runbook.md`; the fifth is
the layering contract in [dependency rules](dependency_rules.md). CI enforces all five:

| # | Gate | Command |
| --- | --- | --- |
| 1 | lint | `python -m ruff check .` |
| 2 | format | `python -m ruff format --check .` |
| 3 | types | `python -m mypy` |
| 4 | tests | `python -m pytest -n auto --dist loadscope` |
| 5 | imports | `lint-imports` |

`pyproject.toml` is the executable source of truth for the import contract, and
`.github/workflows/ci.yml` runs `lint-imports` alongside the other four gates.

### Two things to know before wiring these into CI

**The suite runs in parallel, and the marks are not what makes it fast.** Measured on
`43b0d7f` — this branch's merge of `develop`, so the numbers include #244's deterministic
solver budgets; the commits after it change documentation only — on one developer machine
(Python 3.11.0, 16 logical / 8 physical cores, 2,563 collected tests):

| Suite | Command | Wall clock |
| --- | --- | --- |
| serial | `pytest` | 453 s (7 m 33 s) |
| serial, deselecting `slow` | `pytest -m "not slow"` | ~331 s (derived, see below) |
| **parallel — what CI runs** | `pytest -n auto --dist loadscope` | **121 s** (2 m 01 s) |
| parallel, default distribution | `pytest -n auto --dist load` | 156 s (2 m 35 s) |

Every one of those runs reported the same 2,562 passed and 1 skipped. That equality is the
gate: a parallel run that passes a different number of tests has found an ordering assumption,
not a speed-up.

Locally, use the same command CI does:

```bash
python -m pytest -n auto --dist loadscope
```

`-n auto` is deliberately **not** in `addopts`, so a plain `pytest path::test` stays serial and
starts instantly. `auto` counts *physical* cores, not logical: it created **8** workers on the
16-thread machine above, and will create 4 on a `ubuntu-latest` runner — so CI's wall clock is
longer than the number in the table. Read what the run reports rather than assuming.

**What it costs in CI, measured rather than extrapolated.** Four workers instead of eight, so
the table above is an upper bound on the gain. All runs post-#244 and on the same runner class:
serially, `develop`'s own push runs at `1e89b7c`, `479f4f6` and `95a6f7e` plus five
pull-request runs on branches off them; in parallel, four heads of the branch that turned the
flag on. The two rows below rest on different sample sizes, so each says its own.

| | serial | parallel |
| --- | --- | --- |
| pytest step, whichever interpreter was slower *(3 runs each)* | 407–430 s | **224–235 s** |
| slowest job — what a pull request waits for *(8 serial, 4 parallel)* | 6 m 20 s – 8 m 26 s | **4 m 48 s – 5 m 07 s** |

Neither row overlaps, which is the claim: on the wait, a factor of **1.24 to 1.76**, or 73 to
218 seconds saved. Seven of the eight serial runs sit above 7 m 40 s, so **about three minutes
describes the typical case rather than the floor** — the floor is a little over one minute.

Getting to that took four attempts, which is the other thing worth recording. One pair of runs
suggested 1.32× on one interpreter; the next run of the same tree contradicted it; three runs a
side then gave 1.5 to 1.7; and the fourth through eighth serial observations widened the low end
to 1.24 when one job came in at 6 m 20 s. The direction never moved and the ranges never
overlapped. Any single pair, though, will produce whatever ratio it likes.

**Do not read a per-interpreter number out of this.** Across the three parallel runs the pytest
step was 202, 157 and 224 s on `py3.11` and 235, 235 and 155 s on `py3.13` — overlapping ranges,
and in each run one of the two happened to be the fast one. Runner variance here is larger than
any interpreter difference, so a single pair will produce whatever ratio it likes. Serially the
pinned 3.13 environment does tend to be the slower of the two (383–430 s against 266–407 s), but
that is a tendency and not a factor.

What the table does support is that the parallel runs cluster tightly at the top — 224 to 235 s
whichever interpreter it is — which is what being **floor-bound** looks like: four workers are
already enough for the slowest module to set the wall clock. The floor described below is
therefore not a future concern in CI. It binds now, and it is why the CI gain is a factor of
1.24–1.76 rather than the 3.8× measured locally on eight cores.

**Why `loadscope` rather than the default.** `loadscope` groups a module onto one worker, so the
eleven module-scoped fixtures are built once instead of once per worker that happens to draw one
of their tests. It measured faster despite distributing less freely, which was not the
prediction — the default was expected to win because the heaviest module has no module fixture
to rebuild. The margin is **35 s**, and it widened rather than narrowed as the suite grew: on
`51bbaf6` it was 16 s. Measure before changing this.

**What sets the floor.** Grouping by module means the slowest module is the shortest the run can
be. `tests/unit/test_scenarios.py` is 51 tests and **88 s** on its own, which is 73 per cent of
the 121 s parallel wall clock — so more workers buy almost nothing until that file is split or
its solver budgets come down. That is the next lever, not more parallelism.

The floor rose by 9 s between `51bbaf6` and this measurement, and the cause is worth naming
rather than absorbing: #244 replaced a wall-clock budget with a deterministic one in the rank
solves, so those searches now stop on work done instead of on elapsed time. Two tests in this
module got slower for that reason — 18.3 s to 19.9 s and 13.2 s to 16.9 s. That is the price of
a reproducible stopping point, paid in about 5 per cent of the gate's wall clock, and it is a
better trade than a gate that is fast and occasionally wrong.

**Why parallelism is safe here**, checked rather than assumed: every write in the suite is under
`tmp_path`, and the repository paths tests touch (`docs/`, `web/public/data/`) are read-only; no
test opens a socket or binds a port, and `tests/integration/test_backend_api.py` uses FastAPI's
in-process `TestClient`. The determinism constraint is unaffected because it applies *within* a
solve — CP-SAT is pinned to `num_search_workers = 1`
(`src/squadopt/optimization/optimizer.py`) — not across tests.

**The gate is green at deliberate oversubscription, and that is how a defect was found.**
`pytest -n 16 --dist loadscope` puts two workers on every core. It ran 133 s, 135 s and 135 s
across three runs, each reporting the same 2,562 passed and 1 skipped. Before #244 the same
configuration failed three rank-objective tests, because a solve stopped by a wall clock
returns a different answer depending on the CPU share it received (#239) — and one of those
three, run twice on identical inputs, returned two different squads. The probe is worth keeping
as a technique: it surfaced in a single run what CI would otherwise have delivered as one
random failure at a time over weeks.

**What the marks actually cover.** The nine `slow` tests carry 122 s of the 453 s, which is
where the derived serial figure above comes from (453 − 122 = 331). But of the 30 costliest
items, 21 carry **no** mark and hold another 94 s, so `-m "not slow"` was never going to produce
a fast suite. The clearest evidence that the marks are not tracking cost is that the test CI
lost to contention — `test_a_zero_edge_rank_solve_is_bit_for_bit_the_historical_one`, 7 s — is
one of the unmarked ones. #230 records the list.

**The largest single item is a fixture, not a test.** `test_screening_experiment`'s module
fixture is 23 s on its own — 5 per cent of the serial wall clock — and parallelism cannot
remove it, only move it. It is not, however, on the parallel critical path: the whole module
runs in 29 s against the 88 s that sets the floor, so deleting the fixture outright would not
shorten the gate. Tracked in #233, which stays open on that basis. For contrast, the
session-scoped `baseline_result` fixture (`tests/conftest.py`) does run a full CP-SAT solve, but
the entire module that first builds it finishes in 0.38 s; an earlier draft of this section
named it as a cause of the runtime, which measurement does not support.

Regenerate all of this with `pytest -q --durations=30` rather than trusting the table after the
suite grows again.

**Interpreter coverage is deliberate.** `requires-python = ">=3.11"` and ruff target Python
3.11, while mypy models Python 3.13. CI therefore runs both Python 3.11 (declared dependency
ranges) and 3.13 (the pinned measurement environment in `constraints.txt`).

A dependency added to `pyproject.toml` is still not *automatically* added to
`constraints.txt` — `scipy` arrived that way in #139 — but the two are no longer kept in step
by hand alone. `tests/unit/test_dependency_pins.py` fails when a declared dependency has no
pin, and fails again when a pin falls outside the range it is declared with, which is the same
drift running the other way. Adding the dependency to both files is still a manual step; going
on to merge with only one of them done is not.

The gap was closed on evidence rather than on principle. `jsonschema` had been declared in the
`api` and `dev` extras, imported by `src/squadopt/api/views.py` and used by five test modules,
and was absent from `constraints.txt` together with its whole runtime subtree, while its type
stubs were pinned. Worth being precise about what that cost: no measurement script imports
`jsonschema`, so the committed artifacts were never affected. The 3.13 job is what was
affected — it installs `-c constraints.txt -e ".[api,dev]"` and is described two paragraphs up
as the pinned measurement environment, while resolving a schema-validation library freely
inside `>=4.23,<5`.

## Branch names

`feature/*`, `fix/*`, `docs/*`, `chore/*`, `test/*`. Commits follow Conventional Commits with
the PR number appended by the squash merge — the convention the history already follows, now
written down. Check it against the log (`git log --oneline`) rather than against a commit count
recorded here.

## Tag namespaces

Four namespaces, each answering a different question. They were not designed together — the
first one was in use before any of this was written down — so the point of the table is to stop
a reader in March from guessing which kind of thing a tag is.

| Namespace | Answers | Created by | Example |
| --- | --- | --- | --- |
| `v<semver>` | Which *software release* is this? | release owner, on `main` after the release merge | `v1.0.0` |
| `run-<season>-gw<NN>` | Which tree *executed* a gameweek? | operator, before the capture window opens | `run-2026-27-gw01` |
| `site-<season>-gw<NN>-<decision\|settled\|fix<N>>` | Which artifact was *deployed*? | operator, before dispatching Pages | `site-2026-27-gw01-decision` |
| `v<season>.gw<NN>` | — | nobody, from now on | `v2026-27.gw01` |

The last row is the hazard this section exists for. `v2026-27.gw01` is a **season pointer**
occupying the `v*` namespace, created in #130 before a taxonomy existed. It is not a software
version and does not compare with one. It stays exactly where it is: the runbook's rule is that
a tag is never moved or reused, and quietly re-pointing history to tidy a naming mistake would
be worse than the mistake. Nothing else will be named this way.

There is also one tag that matches no namespace at all: **`site-2026-27-gw01-ui`**. It looks
deployable and is not — `ui` is outside the suffix set the Pages workflow accepts, so the
dispatch was refused by the tag guard and the release was re-cut as
`site-2026-27-gw01-fix2`. The tag stays, inert, for the same reason `v2026-27.gw01` stays. If
you find it in the list, it deployed nothing.

Check the list against the rules rather than trusting this section. Git does this on its own,
so the check runs the same in PowerShell as in a shell:

```console
git for-each-ref --sort=creatordate --format="%(refname:short) %(objecttype)" refs/tags
```

Every tag should be an annotated `tag` object, not a `commit`: the production workflow rejects
lightweight tags outright.

Two mechanical consequences worth knowing:

- The Pages workflow only accepts `site-\d{4}-\d{2}-gw\d{2}-(decision|settled|fix\d+)`. A tag
  outside that shape cannot be deployed, whatever it is called — so an ad-hoc suffix is not a
  naming preference, it is an undeployable release. This has already cost one dispatch.
- `run-*` and `site-*` are per-gameweek and accumulate; `v<semver>` is per software release and
  is expected to be rare. A gameweek that ships no behavioural change adds no `v*` tag.

`deployment_runbook.md` remains authoritative for how `run-*` and `site-*` are created and
dispatched. This section only says what the namespaces *are*.

## Verification

```bash
gh api repos/:owner/:repo --jq '{default_branch, delete_branch_on_merge}'
gh api repos/:owner/:repo/branches/develop/protection
```

Read the answer rather than a copy of it. An earlier draft of this section pasted the six
measured values into a table, which is the same mistake the rest of this pull request exists to
undo: a number committed to a document is right on the day it is written and silently wrong
afterwards, and nothing fails when it drifts. What is worth writing down is how to interpret
whatever the command prints.

**The rule.** Every requirement listed under [Protection](#protection) is asked of the settings.
Where the settings do not supply one, the requirement still stands as an agreement — it is
simply unenforced, and an unenforced agreement is kept by people or not at all.

**How to tell which regime you are in.** Two fields decide whether the ownership table has any
mechanical force:

- `required_pull_request_reviews.required_approving_review_count` — if this is `0`, a pull
  request can merge with no review at all, and GitHub reporting a branch as `CLEAN` means only
  that nothing blocks the button, **not** that anyone approved it.
- `required_pull_request_reviews.require_code_owner_reviews` — if this is `false`,
  `.github/CODEOWNERS` neither requests nor requires a review, so the shared-boundary rule
  (one approval from each of the other two roles) is convention rather than a gate.

While both hold, treat a shared-boundary merge as needing sign-off you have to go and ask for,
and record it in the pull request so the agreement leaves a trace the settings do not.

Two further readings worth knowing. `required_status_checks.contexts` lists which checks
actually block: a job that runs on every pull request but is absent from that list can be red
without stopping a merge. And `delete_branch_on_merge` governs cleanup — while it is off, stale
heads accumulate, and because pull requests are squash-merged git cannot prove a branch was
merged even when its content is in `develop`. Do not prune with `git branch --merged`: it
reports almost nothing as merged, so the reachability test misleads rather than errs on the safe
side. Prune by whether the pull request is closed.

Closing any of these gaps is a protection-settings change, not a code change, and it belongs to
the core-architecture owner.

For the record, as history rather than as current state: on 2026-08-19 twenty-one pull requests
merged with zero required approvals, which is what prompted this section to be written down.
