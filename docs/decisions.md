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
