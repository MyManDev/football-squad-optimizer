# ADR 0024: Release the planning workflow one window at a time

- Status: accepted
- Date: 2026-11-20
- Decider: project owner
- Related: ADR 0017 through ADR 0023

## Decision

The server reads `SQUADOPT_BACKEND_LLMOPT_VNEXT`, disabled by default.
An enabled server advertises `llmopt_vnext: true` in its current league
or public entry capabilities. This grants the one-week workflow. A
three-week confirmation requires the additional current grant
`llmopt_vnext_three_week: true`. The server omits this field unless
both release settings are enabled. An absent, false, stale or unreadable
grant selects the legacy workflow for that window. Read the grants from
the server even when the new one-week calculation would run locally.
No key, query parameter, browser setting or build option activates it.

In legacy mode a fresh confirmed draft uses the established main, two
price and combined plan requests, as applicable. Keep their request
identity, ordering, transport and result presentation. In enabled mode
use the shared run budget, grouped preferences, eligible device work,
plan-aware conversation and verified repairs. The two transfer-package
controls still require explicit opt-in and a separate owner decision.
Neither release setting enters a calculation key.

### Owner decision on 2026-11-21

The first opening covers one week. Three weeks retains its original main,
two price and combined requests, including their order, bodies and cache
identities. The three-week release waits for a separate queue and completion
measurement and an owner decision. These four controls use five environment
variables because package search has its own optional admission gate.

| Server setting | Default | Effect | Required setting |
| --- | --- | --- | --- |
| `SQUADOPT_BACKEND_LLMOPT_VNEXT` | `0` | Enables the one-week workflow, including eligible device calculations, preference tiers, plan conversation and verified repairs. | Current capability for the capture. |
| `SQUADOPT_BACKEND_LLMOPT_VNEXT_THREE_WEEK` | `0` | Enables the advanced three-week workflow. | Master enabled and current three-week grant. |
| `SQUADOPT_BACKEND_THREE_WEEK_PATHS` | `0` | Offers additional three-week paths after the main plan. | Master and three-week workflow enabled. |
| `SQUADOPT_BACKEND_TRANSFER_PACKAGES` and `SQUADOPT_BACKEND_PACKAGE_GATE` | `0` and `0` | The first enables the experimental package search. The second opens its optional search stage. | The package search requires an enabled workflow for the window. Its optional stage also requires the package search. |

Use the window of the draft being confirmed. Switching the draft from one
to three weeks reads the current grants again. A prior one-week grant or
saved run identifier cannot authorize another window. Keep existing drafts
and completed results readable in all four combinations of the two release
settings. A previously admitted job may finish during rollback. Additional
advanced work for a closed window requires a new grant.

Changing the setting back takes effect for new confirmations. Existing
results and job status remain readable in both modes. During rollback a
pending new-mode session can view completed work without scheduling new
stages. Read saved drafts without rewriting previously valid rules or
exposing saved credentials. Keep model communication on the two existing
intent endpoints. Carry the default-closed release control into the
earlier phase branches before their independent integration.

## Acceptance

Exercise the normal browser route against a local server and real worker.
Compare resource transitions with an independent enumeration, including
temporary and permanent chip squads and entitlement renewal. Compare the
two workflow modes and restore older sessions under both settings.
Record queue wait, per-job work and alternative yield using cold and
warm local state on the original twenty member-weeks. Run the measurement
separately from tests and CI. Record omissions and failed cases alongside
the totals. Release activation remains an owner decision.
