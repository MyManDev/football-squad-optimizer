# Contextual football development, 22 September 2026

User-authorized continuation of the five-step football roadmap. Priority is team/role
attack, defensive/clean-sheet components, joint events, and observation-contingent
planning. The existing `football_team_share_v1` remains a frozen comparison arm.
The new arm is `football_contextual_v3`; it must not inherit the rejected stationary
minute transition or full-match player-CS approximation.

## Scope and acceptance, fixed before measurement

1. Carry per-week appearance probability through the planning contract. Consume captured
   feed availability once, before attacking shares are allocated. Existing source-bound
   LLM club-news categories can constrain an information state; do not turn generated
   prose/confidence into invented calibrated playing probabilities. Missing role/event
   sources remain missing, not synthetic observations.
2. Sequential opponent-adjusted attack/defence states with shrinkage and uncertainty.
   Allocate attack to current-club player roles and eligible minutes. Optional captured
   event-channel intensities and taker priorities must be explicit, timestamped inputs;
   without them do not claim separate penalty/open-play/set-piece estimation.
3. Defensive counts use causal context and temporally held-out dispersion estimation.
   Player CS integrates eligible exposure and uncertainty in opposing scoring intensity.
   Bonus/cards remain the explicit conditional residual until event-level training data
   supports separate heads; no invented BPS or shot labels.
4. Shared score intensities and event times, coherent eligible player intervals and
   scorer/assister allocation. Test score conservation, absence, CS after substitution,
   reproducibility, coverage, and analytic-versus-simulation discrepancies. Scenario
   structural validity is not evidence of calibration or superior decisions.
5. Extend the existing restricted action-menu recourse to chip rights, expiry, Free Hit
   restoration and conditional continuations. Information nodes describe observations,
   never future realized scores. Keep fixed compute limits, actual hit accounting and
   explicit approximate terminal-value diagnostics.

Two controls: current historical component family and football v1. Reused development
seasons must be labeled reused; they cannot become an untouched promotion test. Component
losses, 1/3/5-week horizons and realized decision scores are separate. Freeze candidates
and constants before running any historical comparison. No result-selected player/week
pruning, no tuning rejected role transitions on the same evaluation origins. Report
failures, missing data and solver proof gaps rather than excluding them.

Implementation and tests use the existing `codex/football-model-development` worktree.
No root checkout edits, live-state reads, new services/dependencies or automatic model
promotion are part of implementation. Operational release remains a separately verified
step after quality gates and evidence review.

## Implemented boundaries

`build_football_forecast.py --contextual` produces the separately named v3 artifact.
An optional `--rotation-evidence` / `--club-news-source` pair uses the existing digest/span
verified evidence loader. The latest user instruction authorizes the contextual candidate
to use categorical absence and minute limits before prediction. The existing v1 manager-word
advice constraint remains unchanged. No LLM confidence is treated as a probability, and
no future recovery date is invented. A source statement must be resolved and less than
seven days old, with publication/fetch times preceding the decision.
Within a double week, one captured eligibility state is shared: if it is `a` and each
fixture's marginal appearance is `a*p_j`, the weekly probability is
`a * (1 - product(1-p_j))`. Two scheduled fixtures therefore cannot manufacture a second
independent recovery chance. Conditional match appearances remain an approximation.

The official FPL bootstrap response was checked on 22 September 2026. It includes
`penalties_order`, `direct_freekicks_order`, and `corners_and_indirect_freekicks_order`.
The capture producer now retains these ranks by stable player code and snapshot identity.
Unknown ranks remain null and ties are allowed. Ranks do not measure penalty frequency,
conversion, set-piece xG, or historic duties. Accordingly they have no added scoring bonus:
the historical xG already includes those goals and double-counting would be unjustified.
Separate channel rates still need labelled, decision-time evidence before activation.

The new joint sampler conditions on a legal eleven, one goalkeeper and up to five
like-for-like changes. Explicit absent players cannot play; minute-limited starters need
eligible substitutes and learned sub-90 support. Unsupported rosters fail explicitly.
The sampler conserves 990 regulation player-minutes per club, with no red-card paths.
Conditioning changes marginal minute/appearance probabilities. Preview artifacts therefore
report mean and maximum discrepancies for minutes, appearance, goals, assists, CS, DC and
raw points. This is a constrained approximation, not a calibrated match simulator.

An offline bundle can set `contextual: true`, `scenario_selection: true`, and supply `chips`
using `available`, `forced` and `use_windows` from the existing chip contract. Selection
compares a bounded menu using official autosub/captain/chip scores on common worlds. The
first half selects and the other half evaluates that fixed decision. Analytic future
continuation is reported separately. Observation candidates share the same information tree;
their deterministic control is not mixed into an unequal-information comparison.

Observed recourse now carries each chip right/renewal and its expiry. Free Hit restores
holdings and bank, and all branches retain actual purchase/sale/hit accounting. Extra-FT
value is re-solved with the branch's remaining chips, so it measures their joint effect
inside the provided horizon. Zero terminal value remains explicit: no fitted beyond-window
bank/FT/squad/chip continuation, complete season MDP or long-run advantage is claimed.

## Frozen development measurement

The registered run completed all 56 weeks (both seasons GW11–38), 168 component records
(v1, full v3, attack-only ablation), and 72 horizon records (12 origins × 1/3/5-week windows
× two arms), with zero failed folds. Existing causal features and archived outcomes were
reused. Current taker/news records were not backfilled into historical weeks. The final
historical calendar and constructed roster are not verified deadline snapshots.

Equal-gameweek mean point MSE:

| Season | Frozen v1 | Attack only | Full contextual v3 |
| --- | ---: | ---: | ---: |
| 2024–25 | 3.638197 | 3.642108 | 3.652257 |
| 2025–26 | 3.592529 | 3.592009 | 3.597900 |

Full v3 also worsens average goal/assist Poisson log loss and CS Brier in both seasons.
In 2025–26, DEFCON Brier changes from 0.041583 to 0.042631. Future fixture point MSE is
3.562476 → 3.551603 in the first-week window, 3.842480 → 3.843343 over the three-week
window, and 3.931646 → 3.940931 over five weeks. These are fixture losses within each
window, not errors of summed multiweek player points or realized transfer-policy returns.
Missing labels are counted, never zero-filled (23 per arm across three-week origins and
65 across five-week origins). Minute and appearance heads are unchanged when no captured
source restrictions are provided; their historical metrics are therefore unchanged.

**Decision: no live promotion and no default activation.** Keep v1 as the existing football
forecast and retain v3 only as an explicit experiment. Do not retune this candidate on the
same 56 measured weeks. Infrastructure correctness does not rescue weaker prediction losses.
The new scenario selection and chip recourse have structural tests, not measured historical
season-policy superiority. Feed/news/taker effects still require prospective validation.

Reproduction entry point: `scripts/measure_football_contextual.py --archive ... --training ...
--rosters ... --output ...`. It writes the frozen protocol, input/source hashes, every fold's
losses, full future forecasts, failures and completion counts to a new directory.

Official source: [FPL public bootstrap](https://fantasy.premierleague.com/api/bootstrap-static/).

## Engineering verification

Final local Python gates pass: Ruff, strict mypy, three import contracts, and 6,689 tests
passed / 14 skipped. The skipped opt-in capacity, backend-browser, container and publication
checks are not claimed as local passes; one Parquet-engine test is also skipped. Nine
warnings come from the existing Gaussian-process terminal-value tests.
Web gates pass: generated types, lint, formatting, type checking, 1,282 tests passed / two
skipped, build, deployment assets and bundle size. Playwright: 88 passed / two skipped with
two workers. API/worker fixtures exercise both model versions, 1/3/5-week windows and
Top100 preferences without using live operational state.

A historical constructed 752-player roster completed a three-week CLI rehearsal with
Triple Captain rights, two candidate plans and an OPTIMAL control solution. There were
64 common match worlds, split into 32 selection and 32 evaluation draws. Mean absolute
analytic-versus-sampled player-fixture gaps were 3.11063 minutes and 0.17018 raw points;
maximum gaps were 19.42544 minutes and 1.40607 points. These include Monte Carlo noise
and the lineup-conditioning approximation. They do not establish marginal calibration.
The chosen action was the control; no season-policy improvement is inferred.

No production artifact was replaced and no live model was promoted. Separate goal-channel
rates, prospective news effects, red-card paths, calibrated substitution hazards, and a
fitted joint terminal value remain outside the verified implementation.
