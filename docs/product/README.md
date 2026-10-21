# Product and member experience

The visitor enters league `352490`, selects their own member record, inspects their held
squad and chooses a rival strategy or planning window. The selected identity is a local,
unverified claim. Other leagues are not enabled by merely changing the input field.

The direction since 2026-10-05 is device-first computation for any listed league (issues #978
and #981). Today the member's browser solves the one-week plan, chip weeks, both rival
strategies and the Top 100 weight from the published device-plan table; three- and five-week
windows still come from the advice backend. The weekly run takes its leagues from
`config/leagues.json`, which lists one league; the second league is to be named on #981.

| Question | Reference |
| --- | --- |
| Which product and research phases are implemented or gated? | [Product roadmap](roadmap.md) |
| How is the frontend developed and checked? | [Web README](../../web/README.md) |
| What opens from a player plate, and when do players move? | [Player details and pitch movement](player_details.md) |
| What does a member's rank movement compare? | [Captured rank movement](member_rank_movement.md) |
| Which strategy hypotheses are being tested? | [Strategy screening declaration](../strategy_screening_prereg.md) |
| What was measured for strategy behavior? | [Strategy bench record](../strategy_bench.md) and [declaration](../strategy_bench_prereg.md) |
| What does a projection horizon promise? | [Projection horizon contract](../projection_horizon_contract.md) |
| Which API and published-view schemas exist? | [Contract directory](../contracts/) |
| How does the live member record consume a measured week target? | [Member series](../member_week_series.md) and [horizon contract](../contracts/member_week_horizon_v1.md) |
| How do pages receive a new publication? | [Weekly runbook](../weekly_runbook.md) |
| What does the member's device solve, and from which inputs? | [Device-plan contract](../contracts/league_device_plan_v1.md) |
| Which leagues does the site serve, and how is one added? | [Configuration guide](../../config/README.md) |
| Which advice routes does the backend serve, and what replaces each on the device path? | [Advice backend endpoints](../operations/advice_backend_endpoints.md) |

A published plan, a newly computed answer, a feasible plan and a proven optimum are distinct
states. Preserve that distinction, along with unknown versus zero and held versus recommended
captain/bench data. Product claims should point to their measurement and source limitations.

New product prose can live in this directory; existing versioned schemas and measurement
records retain their current paths. [All documentation](../README.md).
