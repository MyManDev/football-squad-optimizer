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
