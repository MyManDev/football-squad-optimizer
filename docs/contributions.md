# Player contributions

The `/contribute` page accepts observations about the complete captured FPL roster through
Team → Position → Player filters. This includes players outside the optimizer's candidate
pool. Changing team or position clears the player and their draft to prevent misattribution.
The capture timestamp is shown; this is a published roster, not a real-time feed. It uses the configured
advice API origin and its existing CORS allowlist. Comments do not enter prediction, news,
optimizer, MDP or training inputs. Display names are self-declared, not verified accounts.

An explicit publication checkbox is required. The server validates the season/player against
the published roster, limits a JSON body to 12,000 bytes and a comment to 1,500 characters, and
accepts only HTTPS source links. It never fetches those links. React renders comments as text;
source links use `noopener noreferrer nofollow ugc`. Moderators should check sources before
approval and avoid publishing personal information or unsubstantiated private health claims.

## Persistence and moderation

The roster needs no new database. Generate `data/players.json` in the publication from an
immutable FPL capture, alongside fixture publication, using:

```console
python -m scripts.build_player_catalog --snapshot-root data/snapshots --snapshot-id <capture-id> --out <public-directory>
```

This producer includes every element, uses persistent player codes (preserving existing
comment associations), and validates team and position identities. Publish this file with
both the site and backend checkout. Missing or invalid catalogs return 503; the API never
silently falls back to the restricted optimizer pool. Refresh it when publishing a new
capture, including transfers and new registrations. Comment storage remains separate.

The existing backend composition creates `contributions.sqlite3` under its configured store
root on first access. SQLite is in the Python standard library; no additional dependency or
service is required. This file is separate from prediction artifacts and advice queues.
Deployment must preserve this backend directory and restrict filesystem access to the host
operator. The public read returns only approved comments, newest first, with a limit of 50;
the API's optional `before` cursor supports older pages. The UI currently shows the latest 50.
Read responses are not cached, so retracted comments disappear on refresh.

New submissions return 202 `pending`. Approval is a host operation using existing OS access,
not an unauthenticated admin web page. With the backend environment loaded:

```console
python -m scripts.moderate_contributions pending
python -m scripts.moderate_contributions approve 42
python -m scripts.moderate_contributions reject 42
```

For isolated testing, `--db <existing-test-database>` selects an explicit database. The CLI
refuses a missing file. Rejection can retract a previously approved comment. Moderation does
not delete records; preserve the file for audit and use SQLite's backup API for consistent
backups while the service is running. Review the pending inbox regularly. There is no email
notification, authentication/account system, automatic approval or new scheduled task.

## Abuse limits and operational limits

Each daily keyed visitor digest can submit three comments per hour; the entire site accepts
at most 50 per hour. Transactions serialize quota checks and insertion across concurrent
requests. An identical pending submission within 24 hours returns the same receipt, avoiding
duplicates after a lost response. A hard limit of 10,000 retained comments fails closed.
Quota refusal returns 429 and Retry-After 3600; unavailable storage returns 503. The browser
keeps failed text in memory and only clears it after a validated pending receipt.

Raw visitor addresses are never stored in the database. Daily HMAC digests require the random
local database salt; quota entries older than 24 hours are removed on the next accepted
transaction. These are abuse controls, not proof of identity. Shared networks share a quota,
and distributed attackers can still exhaust the global quota. Existing proxy trust must stay
restricted; do not trust client-supplied forwarded headers. Infrastructure access logs retain
their existing policy. No new analytics are added.

## Fixtures and release acceptance

The fixtures page shows the first gameweek with an open deadline or an unfinished future
kickoff, and its numbered successor from the published calendar, above every earlier week.
Closing the FPL deadline does not hide remaining weekend fixtures. The list includes the
capture date; this is not a real-time scores service. The sidebar links it on every screen
(a 264px column from 1180px, a 72px icon rail from 600px, a drawer below that), and phones
also have a 'Fikstür' button in the sticky phone bar. The shell carries no league-wide
fixture rail. Advancing the clock selects later weeks but never invents a score,
reschedules a fixture, edits the publication or runs a capture.

Verify browser submission, the pending/public separation, approval, reload, retraction,
storage restart, invalid requests, quotas and errors with an isolated database. Production
checks should use the real API player list and read-only comment views; any production test
comment must be clearly labelled and kept unapproved/rejected. Do not approve invented player
news for a smoke test. The UI alone cannot enable this feature: deploy the tested backend
revision through the standard guarded rollout as well as the static site.
