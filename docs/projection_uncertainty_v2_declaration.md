# Declaration: `projection_uncertainty_v2` — position by fixture group

The uncertainty layer's #38 decision ([issue38_calibration_decision.md](issue38_calibration_decision.md))
named the next axis of the operational conformal calibration and asked that it arrive as
its own declaration. This is it. The evidence it rests on is
[fixture_group_conformal_note.md](fixture_group_conformal_note.md); the contract is
implemented and measured on the control; it is **not yet the default** the risk screening
and the live path use, and this document says what that step needs.

## The contract

`squadopt.uncertainty.UncertaintyConfig(grouping="position_fixture_group",
contract_version="projection_uncertainty_v2")`:

- **Groups**: position × fixture group, `single` (one fixture) and `double_plus` (two or
  more), one conformal radius per cell — the same finite-sample order statistic
  (`ceil((n+1)·q)`, capped at n) as v1 — with a fallback to the position when a cell has
  fewer than `min_group_observations` rows and to the pool when the position does too.
  Sources: `position_fixture_group`, `position_fallback`, `pooled_fallback`.
- **Blanks** (zero fixtures) project zero by construction: excluded from calibration,
  applied with a zero radius and source `blank_zero`.
- **Calendar required**: every projection row carries `fixture_count` at fit and at
  apply; a table without it is refused. `attach_fixture_counts_to_folds` joins the
  published calendar to walk-forward folds by season, gameweek, and club.
- **v1 untouched**: `grouping="position"` is the default; its configuration fingerprint
  reproduces the committed control record (`238734…`, tested); a v1 calibration carries no
  fixture cells and its fingerprint payload is unchanged.
- Evaluation under v2 reports metrics per fixture group and per cell alongside the
  position metrics; the calibration record carries the cells.

## Measured on the control (development-internal, `docs/control_uncertainty_calibration_v2.md`)

Fitted on 2021-22 … 2023-24 (110 folds), scored frozen on 2024-25 (37 folds; the season
had few doubles: 364 held-out double rows). Cells (rows, radius): DEF single 3.8 (23,637)
/ double 5.6 (1,581); MID 3.2 (30,011) / 4.6 (2,007); FWD 3.8 (8,905) / 5.6 (619); GK 2.8
(7,843) / 3.6 (541) — every cell fitted from its own rows, no fallback needed.

| Held out 2024-25 | v1 (position) | v2 (position × fixture group) |
| --- | ---: | ---: |
| overall coverage / width | 0.9096 / 6.85 | 0.9100 / 6.89 |
| single coverage / width | — | 0.9107 / 6.85 |
| double_plus coverage / width | — | 0.8626 / 9.83 |
| DEF/double_plus | — | 0.9180 (n=122) |
| MID/double_plus | — | 0.8373 (n=166) |

Read with the four-season chronological measurement (0.849 → 0.901 on 1,265 doubles): on
2024-25's few doubles v2 reaches 0.86, MID's 166 doubles being the short side, with
overall coverage and width unchanged. It is the honest interval on a double, wider by
about 45%, and it costs the singles nothing.

## Operational default (2026-08-18, later the same day)

The runners now default to v2 and carry the calendar themselves:

- `scripts.run_risk_screening --uncertainty-grouping` defaults to
  `position_fixture_group`; `RiskScreeningConfig.uncertainty_grouping` selects the
  contract (its default stays `position`, so recorded screenings and their fingerprints
  reproduce; the fingerprint payload gains the key only when it is not the default), and
  the runner attaches the archive calendar to every fold (`calendar_from_archive`,
  `attach_fixture_counts_to_folds`). The risk optimizer accepts v2 group labels
  (`<position>/<group>`) and sources (`position_fixture_group`, `blank_zero`).
- `scripts.run_control_uncertainty_calibration --grouping` defaults to v2 and writes the
  `_v2` record; the v1 record is left as it was.
- Live: `recommend_current_squad --risk-double-gameweek-scale` (default 1.45) reads the
  capture's calendar (`fixture_counts_by_player`) and widens double-gameweek players'
  scenario spread; the report states it instead of the calendar-blind limit.
- `UncertaintyConfig()` itself keeps `grouping="position"`; `OPERATIONAL_UNCERTAINTY_
  GROUPING` names the operational choice for callers that fit a calibration for use.

## What is and is not changed by this declaration

- **Available**: v2 can be fitted, applied, and evaluated; the control calibration
  script runs it with `--grouping position_fixture_group`.
- **Library default unchanged, runners on v2**: `UncertaintyConfig()` is still v1 so the
  recorded v1 artifacts reproduce; the risk screening and control calibration runners
  default to v2 with the calendar attached, and the live risk layer widens doubles from
  the capture's calendar (see "Operational default" above).
- **Stated in the live report meanwhile**: an available live lower tail now carries a
  stated limit — the residual history is calendar-blind, so a double gameweek's tail is
  optimistic by roughly the measured undercoverage — instead of leaving it silent, as the
  #38 decision asked.
