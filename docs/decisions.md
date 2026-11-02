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

## 2026-10-12: An enterprise system with a research arm

Decision: the project is treated as an enterprise and academic system, not an experimental
one, and the codebase is to read that way. From this date, new work follows clean-architecture
and scalable-architecture principles. Experimental code whose study has concluded leaves
develop, and research that continues stays clearly separated from the product.

Reason: the system is now documented and reported on as a whole, so its layout, names and
enforced boundaries are part of how it is judged.

What follows from it: #1080 removes dead code and the runners of concluded studies. The
repository map, the folder guides and the named rings arrive with
[ADR 0010](architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md),
which the owner accepted on 2026-10-13: the named rings, their enforcement, the ratchet rule and
the deferred moves with their triggers.

Source: the owner's direction to the maintainers on 2026-10-12, and
[PR #1080](https://github.com/MyManDev/football-squad-optimizer/pull/1080).

## 2026-10-13: The Phase 2 moves of ADR 0010 land now

Decision: the Phase 2 moves of
[ADR 0010](architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md) are
not held for their triggers. The six laboratory modules leave `application`, `integration.py`
folds into `application`, `live`, `data`, `prediction` and `features` get their guides, the
record tests read `docs/research`, the ratchets come into force, and the tests that keep the
script catalogue, the package guides and the documentation complete are added. They are made
together on one branch rather than each in its own pull request after the GW7 publish. The
accepted record is not edited; this entry is where its timing changed.

What still holds is every condition that is not about time:

- The completeness tests fail pull requests in flight, so they are announced on issues #1012
  and #978 before they merge.
- The guides of `data`, `prediction` and `features` are in the data owner's zone and need his
  agreement.
- The change touches `live/` and `prediction/`, so it does not merge inside the
  [live-path freeze window](architecture/ownership.md#live-path-freeze-window), and it does not
  merge while a weekly publish run is in progress: a merge during a run stops that run's
  publication.

Reason: on 2026-10-13, after accepting ADR 0010, the owner asked for Phase 2 to be done now and
said that fixing the architecture directly is the top priority.

Source: the owner's direction to the maintainers on 2026-10-13.

## 2026-10-13: ADR 0011 accepted

Decision: the architecture is fixed directly, and this is the first priority. The owner
accepted [ADR 0011](architecture/decisions/0011-storage-ports-and-platform-split.md): storage
ports declared in the ring that consumes them, with file adapters in `platform`; the vocabulary
half of `data` in named modules, with `data` kept as one package; `platform` split into seven
subpackages by deployment unit, which supersedes the deferral of that split in ADR 0008; no file
IO in `contracts` or the decision core; a public CP-SAT driver; one resolver for schema paths;
a shim policy with permanent operator entry points and names frozen until the planner chain's
final reading; and merge discipline around deadlines and runs. It amends two triggers of ADR
0010's deferred moves and answers its open questions 1, 2 and 4; question 3 (version 2.0.0)
stays open.

Reason: ADR 0010 listed the known violations with remedies but deferred most of them behind
triggers or open questions. The owner's direction of 2026-10-13 makes the fixes the next work,
so the remedies needed one record that decides them and the order they land in.

Source: the owner's acceptance of 2026-10-13, and
[ADR 0011](architecture/decisions/0011-storage-ports-and-platform-split.md).

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

## 2026-11-01: The second league goes live at GW11, and 352490 follows at GW12

Decision:

1. League 755941 (77 members, rehearsed on #981 in comment 6327708004) is the second
   league. It goes live with `menu: device` in the GW11 run. This replaces the 20 to 50
   members of decision 4 of 2026-10-07.
2. League 352490 moves to the device menu in the GW12 run, one week after 755941. This
   replaces decision 2 of 2026-10-07, and #981 step 8 lands with it. The server keeps
   one baseline record per entry (#982).
3. The readings that read 352490's full-menu advice records keep their dates and lose
   the weeks from GW12 on. The price honesty reading at GW9 is unchanged, and the one at
   GW15 pools GW4 to GW11 and lists GW12 to GW15 as not read. The Top 100 readings at
   GW12 and GW20 read the player level as registered, and their plan level ends at GW11.
   The protocols stay as written; each record states its shortened input.

Reason: the owner handed the program to İbo on 31 October, and İbo brought step 8 forward
on 1 November so that 352490 stops being solved on the server once a second league has
run a live week on the device.

Source: [the handover](https://github.com/MyManDev/football-squad-optimizer/issues/978#issuecomment-6548175771),
[the decisions on #981](https://github.com/MyManDev/football-squad-optimizer/issues/981#issuecomment-6559338892)
and [the readings calendar](https://github.com/MyManDev/football-squad-optimizer/issues/1122).
