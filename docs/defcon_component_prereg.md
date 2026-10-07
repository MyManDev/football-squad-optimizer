# Default projection DEFCON component preregistration

Status: declaration for #1000, owner decision B recorded on 2026-10-07. This is
the Q3 record for #872. It authorizes a measurement, with promotion conditional
on the rule below. It changes neither the default nor a member page.

The author opened no capture taken after 2026-10-10T10:00:00Z. The only live
payload inspection for this declaration was the GW1 to GW5 field structure in
`fpl-live-20260922T214539Z-364991a4f832`. Those five weeks were already read and
are development data. No 2025-26 input was opened. No scored-week outcome was
opened. The declaration, including all constants below, is frozen at merge.

## 1. Labels and admissible inputs

The sole season is 2026-27. No 2025-26 data, model, summary, fitted parameter or
derived label is admitted. No historical archive is an input to this component.
The existing default handoff remains the comparator even though its own model
was fitted on its declared older seasons.

Read awarded DEFCON points from each settled `event-gwNN-live.json`:
`elements[].explain[].stats[]`, selecting `identifier == "defensive_contribution"`
and taking its `points`, indexed by the explanation's `fixture` and the element's
season id. `stats.defensive_contribution` is a count, not the awarded points label.
The observed award entry has `identifier`, `points`, `value` and
`points_modification`; the GW1 to GW5 examples have `points == 2` and
`points_modification == 0`. Require zero modification for every admitted award;
an unexplained modification is invalid input rather than a revised label rule.

An appearance is fixture minutes greater than zero, using the same fixture's
explanation entry with `identifier == "minutes"`, field `value`. A played
fixture with a complete explanation and no DEFCON award entry has zero DEFCON
points. A player with gameweek minutes zero has no appearance and contributes
no fit row. Duplicate player-fixture records, inconsistent fixture ids, negative
minutes, missing required fields or awards outside the captured position award
are invalid. A positive-minute fixture needs its minutes explanation. For a
double, gameweek minutes without fixture explanations cannot identify appearances
and are invalid; never split a gameweek total across fixtures by assumption.

Resolve season ids to persistent player codes and positions through the decision
capture's bootstrap. Unmapped historical elements are excluded from both player
and position fitting counts, with their ids and count recorded. Position fitting
uses the position that this capture assigns, with DEF, MID and FWD separate.
Goalkeepers supply neither rate estimates nor additional points. The existing
DEF 10 and MID/FWD 12 count threshold in `football_history.py` is checked on
GW1 to GW5 only as a schema cross-check; it never supplies the award label and
is not applied to a scored-week outcome.

## 2. Fixed additive component

For target week w, fit only completed, settled fixtures in gameweeks strictly
before w, present in that week's decision capture. Require their kickoff and
settlement to precede w's deadline and the capture to precede that deadline.
The capture's bootstrap event must be finished and its fixtures finished with
`finished_provisional == true`; absent or incomplete history makes that week's
inputs missing. Reading an outcome captured at or after w's deadline as a fit
input is refused. GW1 to GW5 may be fit rows but are never scored.

For position p, let A_p be its number of prior fixture appearances and B_p the
number receiving a positive valid DEFCON award. Define r_p = B_p / A_p. Each
required position must have A_p > 0; otherwise the week has missing fit inputs.
For player i, let A_i and B_i be the analogous prior counts. Fix the prior weight
K = 20 fixture appearances, and use:

```text
r_i = (B_i + 20 * r_p) / (A_i + 20)
term_i,w = sum over captured fixtures f in week w of (q_i,w * r_i * d_p)
```

Here q_i,w is the published base handoff's unconditional `appearance_probability`
for this player-week, used unchanged for each scheduled fixture, and d_p is
`SeasonRules.scoring.defensive_contribution[p]` from the decision capture's
`game_config`. Require finite q in [0, 1] and a nonnegative integer d_p. No extra
minutes, starter, fixture-difficulty or Top 100 model is fitted. A player with no
prior appearance receives r_p. A blank has no summands and returns zero; GK
returns zero. A double has two summands. Every scheduled fixture contributes
once regardless of opponents; there is no cross-fixture cap or union adjustment.

Add the term to unconditional base expected points in a copy of the handoff.
The production `project` path applies the capture's availability once, to the
whole candidate as it does to the whole comparator. Never add the unconditional
term to an already adjusted forecast. Preserve the base's roster, fixture counts,
appearance and minutes fields and evidence identity, and record base fingerprint
and component input hashes. No parameter, prior weight or comparison changes
after any GW6 or later outcome has been inspected. Mechanical use of earlier
settled 2026-27 weeks as later targets' fit rows is permitted by this fixed rule;
it is not a diagnostic reading or a tuning opportunity.

## 3. New versions

| Published base | Candidate version |
| --- | --- |
| `phase_c_control_components_v1` | `phase_c_control_components_defcon_2026_v1` |
| `phase-c-component-elite-top100-v1` | `phase-c-component-elite-top100-defcon-2026-v1` |

The term is identical for both bases. Existing version names retain their meaning.
The candidate fingerprint binds its base fingerprint, this declaration's digest,
the version and decision input hashes. Neither candidate is promoted by this
declaration or by the runner PR.

## 4. Weeks, capture selection and one reading

If this declaration merges strictly before 2026-10-12T19:00:00Z, score GW6 to
GW12. Otherwise score GW7 to GW13, with no retrospective addition of GW6.
The planned GW12 last match was 2026-11-29T16:30:00Z in the fixture file captured
2026-10-02. The capture rule, rather than that scheduled time, controls if
fixtures move. In the fallback window substitute GW13 for GW12 everywhere below.

For each scored week use the immutable capture and default handoff that actually
supplied the week's published final pre-deadline advice. The published capture id
must match the handoff, target week and roster. If more than one publish preceded
the deadline, use the last pre-deadline publish. Require the selected capture and
handoff to have existed before the deadline, and retain the publication's identity
record. No alternate, replay or bare-component handoff replaces the published
default. Candidate replay after the week is permitted only from that exact
pre-deadline capture and handoff under this already frozen deterministic rule.

Read the gate once, using the first retained 2026-27 `fpl-live` capture after
the final scored week's last actual match for which every fixture of every
scored week is settled: the fixtures have `finished` and `finished_provisional`
true, their events are finished, and their event-live payloads are present.
Select the earliest capture instant satisfying those conditions, breaking an
equal instant by snapshot id. Later captures do not replace it or repair missing
weeks. The owner runs the reading on his machine with his approval, outside any
Tuesday settle or Friday publish. Link this reading window on #998's calendar.

`--check-inputs` after GW7 and GW10 reads only capture identity, bootstrap,
fixtures, handoff identity, retained publication identity and payload inventory
and checksums. It opens no scored-week event-live payload, computes no candidate
error, ranking or verdict, and reads no outcome. The output identifies which
weeks can be paired and which fixed inputs are absent. No reading mode runs
before the declared settled capture is available.

## 5. Population and missing-week rule

Include every DEF, MID and FWD in the selected published default handoff, including
zero-minute outcomes. Realized total points are `stats.total_points` from the
declared settled capture. Map by persistent player code; a player absent from
that settled capture is dropped from both arms, with ids and counts recorded.
Use the decision capture's position for both arms. Do not restrict to a selected
squad, appearance, minutes bucket or Top 100 holding.

A week is missing when its selected decision capture, published default handoff,
publication identity or deadline proof is absent or inconsistent; its required
fit history, fixture explanation, appearance field or scoring rules are invalid;
its settled event-live payload is absent or incomplete in the declared reading
capture; or its paired population is empty. Missing weeks are excluded from both
arms, with a single named reason and supporting identity recorded. They are never
backfilled and never replaced by another capture. An invalid roster, duplicate
key or forbidden season fails input validation; it is not silently converted to
a scored zero. Target fixture counts and settled realized fixtures must agree;
otherwise that week is missing. A blank remains a valid paired zero-term week.

## 6. Comparator and error calculation

Compare the handoff that the week's publish used against that same handoff plus
the fixed component. Both pass through the same captured availability rule.
For each paired player-week calculate squared error of decided expected points
against realized total points. Average within each week, then average the weekly
means with equal gameweek weights. Define delta_w as candidate weekly MSE minus
comparator weekly MSE, and delta as its equally weighted mean. No pooled
player-weighted MSE substitutes for this gate.

## 7. Fixed pass rule

First count valid paired weeks. Fewer than 5 of the declared 7 gives
`insufficient_evidence`, with no promotion. With at least 5, `passed` requires
all of the following:

1. The upper endpoint of a two-sided 90% percentile interval for delta is strictly
   below zero. Generate exactly 10,000 draws using NumPy `Generator(PCG64(20261007))`.
   Sort available gameweeks, sample that many whole gameweeks with replacement
   in each draw, and average their delta_w. Use `quantile` with `method="linear"`
   at 0.05 and 0.95. Preserve each entire week's paired population in every draw.
2. DEF within-position Spearman is not lower by more than 0.005:
   candidate minus comparator is greater than or equal to -0.005.
3. MID within-position Spearman satisfies the same -0.005 boundary.

Rank only within each week-position, as `_rank_agreement` in
`live_projection_audit.py` does, with average ranks for ties and the final
mean weighted by the group's paired player count. Use identical groups in
both arms: at least three players and at least two distinct realized and
forecast values in each arm. Record every excluded group. If either required
position has no valid common group, its rank gate is undefined and the verdict
is `failed`. FWD ranking is reported but is not a gate.

With at least 5 weeks, any other outcome is `failed`. Do not select another
interval, seed, population, shrinkage weight, window or version after the verdict.
A successor needs a new declaration and scores only deadlines after its merge.

## 8. Reports, retention and consequences

Report all weekly MSEs, deltas, the interval, both rank means and group counts,
the scored and missing weeks and dropped players. Report forecast DEFCON term
against awarded DEFCON points by position, both before and after availability.
These diagnostics do not gate promotion. Report the audit's prior-minutes buckets
unchanged: `none`, `under_30`, `30_to_60`, `60_and_above`, using only each decision
capture's prior history to compute average minutes per preceding gameweek.

The reading writes `docs/research/defcon_component_reading.md` and `.json`, with
code commit, declaration digest, selected captures and handoffs, publication
identities and all input hashes, the fixed constants and verdict. Add its row to
`docs/measurements_index.md`, and merge the record within seven days of the
declared first settled capture. A saved completed record prevents a second gate
reading. A rejected input check is recorded without substituting later evidence.

Only `passed` authorizes a separate wiring PR, reviewed by İbo. It pins both new
versions in `IN_SEASON_CONTROL_MODEL_VERSIONS`, makes the weekly handoff builder
produce them, and keeps them outside `_TRAINED_WITHOUT_DEFCON`. Keep the
scoreboard's bare `phase_c_control_components_v1` baseline. Change no `web/src`
file. The release to main still needs the owner's yes. Neither a runner nor a
reading changes the default. On `failed` or `insufficient_evidence`, leave the
promotion set unchanged, link the reading record on #1000 and close only after
the issue's other finish conditions hold.

The component and runner are a separate PR after the GW6 publish, before
2026-10-23T17:30:00Z, with İbo's review. The input checks wait for the GW7 and
GW10 publishes. This declaration may merge before the GW6 run or after its
publish is complete, never during a weekly run. No PR is enqueued by this work.
