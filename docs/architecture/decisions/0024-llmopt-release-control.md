# ADR 0024: Select the planning workflow with one server setting

- Status: proposed
- Date: 2026-11-20
- Decider: project owner
- Related: ADR 0017 through ADR 0023

## Decision

The server reads `SQUADOPT_BACKEND_LLMOPT_VNEXT`, disabled by default.
Only an enabled server advertises `llmopt_vnext: true` in its current
league or public entry capabilities. The page selects the legacy workflow
when the field is absent, false, stale or unreadable. Read the setting
from the server even when the new one-week calculation would run locally.
No key, query parameter, browser setting or build option activates it.

In legacy mode a fresh confirmed draft uses the established main, two
price and combined plan requests, as applicable. Keep their request
identity, ordering, transport and result presentation. In enabled mode
use the shared run budget, grouped preferences, eligible device work,
plan-aware conversation and verified repairs. The two transfer-package
controls still require explicit opt-in and a separate owner decision.
The master setting never enters a calculation key.

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
