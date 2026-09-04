# Projection Horizon Run

- Contract: `projection_horizon_v1`
- Snapshot: `fpl-live-20260813T201143Z-55789a780186` captured 2026-08-13T20:11:43Z
- Model: `squadopt-deterministic-baseline@opening-carry-over-v1`
- Post-processing: `captured_availability_rule_v1+linear_fixture_count_scaling_v1`
- Horizon fingerprint: `217d8be03d202a6c957e6405b23464e1e4158a0ab28486a1614cdb9c7f7ca27a`

| Gameweek | Players | Total xP | Blank rows | Double rows | Fixture fingerprint |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 584 | 966.02 | 0 | 0 | `7d9083a85e2b…` |
| 2 | 584 | 966.02 | 0 | 0 | `f06202a4ddee…` |
| 3 | 584 | 966.02 | 0 | 0 | `7d9083a85e2b…` |
| 4 | 584 | 966.02 | 0 | 0 | `f06202a4ddee…` |

## What this run shows

Every gameweek projects the same total, and that is the correct answer rather than a defect. At capture time the published calendar is uniform: each club has exactly one fixture in every gameweek. Blank and double gameweeks are created later, by postponements and cup progression, so a capture taken before the season starts cannot show them.

The consequence for planning is worth stating plainly: from an opening capture, the calendar contributes nothing to a horizon, and any advantage a transfer plan finds over a myopic one comes from price and transfer dynamics rather than from fixture variation.

## Limits

This is planning input, not gate evidence. The frozen evaluation objective is single-gameweek realized squad points, and nothing here measures how far a multi-gameweek projection drifts.

It will drift. Expected minutes for a later gameweek are computed from what was known at the decision point, so injuries, rotation and suspensions in between are unseen and the projection grows overconfident as the horizon lengthens — by an amount nobody has measured yet.

The table is local and not committed; it derives from a third-party payload and the pinned archive.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.build_projection_horizon
```
