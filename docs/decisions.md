# Product and operations decisions

This file is maintained by hand and versioned in Git. Record each decision with its date,
reason and issue or PR. The website links here; it does not write to this file.

## 2026-09-14 — An unlisted admin entry point

Decision: keep the member navigation focused on the league entry page. The measurement
archive remains at `/analysis`, reached through `/admin` or a direct link.

The admin page is unlisted, not protected. No password or authentication is provided.
Operational state remains on `/status`; the admin page links to that existing view.
Decision records stay in this file, with no browser editor or local storage for decisions.

Reason: give research and administration their own entry point while preserving shared
analysis URLs and the production smoke path. This changes no measurement content or rules.

Source: [Issue #550](https://github.com/MyManDev/football-squad-optimizer/issues/550).

## 2026-09-26: The measurement archive page is removed

Decision: the site has no measurement archive. `/analysis` is not a route, `/admin` does not
link to it, and the page, its copy and the script that built its index are deleted. This
replaces what the 2026-09-14 entry says about `/analysis`. Its admin entry point stands: the
admin page is unlisted, not protected, and links to `/status` and to this file.

The measurement records themselves do not change. They stay in `docs/`, listed by
`docs/measurements_index.md`.

Reason: #716 took the route and the admin link off the member site, because the archive
served copies of the laboratory's records, and some of them carry wording the member site
does not allow. #815 then removed `/analysis` from both deployment smoke lists. The page stayed
in the tree without a route, tested but never shipped, until #854 deleted it.

Source: [PR #716](https://github.com/MyManDev/football-squad-optimizer/pull/716),
[PR #815](https://github.com/MyManDev/football-squad-optimizer/pull/815) and
[PR #854](https://github.com/MyManDev/football-squad-optimizer/pull/854).

## 2026-10-07: Weekly operation and the next development steps

Decision:

1. The owner runs the Tuesday settle and the Friday publish through GW20. Each
   delegated stage requires his approval for that run. Until the owner says
   otherwise, the PC1 decide step and the C2 pair check run the same way. After
   GW20 the weekly run moves off his PC (#1010).
2. League 352490 keeps the full server menu through GW20. The price honesty
   readings at GW9 and GW15 and the Top 100 plan readings at GW12 and GW20 retain
   their records; #981 step 8 waits until then.
3. İbo reviews and agrees to changes under `src/squadopt/planning/`, following
   Astra's departure (#984 step 3).
4. The second league for #981 is a classic league in which the owner or İbo plays,
   with about 20 to 50 members. It must be named on #981.
5. The manager's word stays as it is until #524 widens club-news coverage. There
   is no weekly club-news stage; #930 items 4 and 10 (steps 7 and 8 of #1006)
   wait until #524 closes as done.
6. Price changes are measured before entering the planner internally. Members
   see no price forecast. #1013 fixes the measurement and the two pass conditions.
7. The forum is out of scope this season. The terminal value duplicate, copula
   and opening two-part research debts are closed. The rival behaviour model is
   closed and reopens when, in a listed league, the gap between a member and the
   default rival passes the strategy band edge re-measured in #1002. For league
   352490 this is expected around GW30.
8. The strategy names are `En çok puan` / `Most points`, `Farkı koru` / `Hold the gap`
   and `Farkı kapat` / `Close the gap`. The window label is `Plan süresi` / `Plan length`.
   The named instruction is `En çok puanı seçin` / `Select most points`. The slugs
   `saf-puan`, `ortak-koru` and `fark-yarat` remain unchanged.

Reason: preserve the owner's 7 October decisions in one versioned record, including
the work that is closed and the conditions for later development.

Source: [Issue #1005](https://github.com/MyManDev/football-squad-optimizer/issues/1005),
[the owner's names](https://github.com/MyManDev/football-squad-optimizer/issues/1005#issuecomment-6044633550)
and [the program](https://github.com/MyManDev/football-squad-optimizer/issues/1012).
