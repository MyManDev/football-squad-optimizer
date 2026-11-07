# ADR 0013: Deadline reminders by Web Push, with no accounts

- **Status:** accepted by the owner on 2026-11-07 ("BUNU YAPALIM", on the proposal of a
  reminder three hours before each deadline, with the subscription in D1 and no user name).
- **Date:** 2026-11-07
- **Decider:** the owner
- **Related:** [ADR 0004](0004-cloudflare-pages-deployment.md), [ADR 0012](0012-fpl-forwarder.md),
  [`push_subscription_v1`](../../contracts/push_subscription_v1.md),
  [`fixtures_v1`](../../contracts/fixtures_v1.schema.json)

## Context

A member decides once a week, and the decision has a deadline. Nothing brought them back to the
site before it: the site has no accounts, sends no mail and keeps no address. The owner's
direction is that the one thing that brings a member back before the deadline is a reminder on
their device, and that it must not cost the visitor an account or the site a user database.

The site is static on Cloudflare Pages (ADR 0004). The FPL forwarder (ADR 0012) showed the shape
a same-origin Worker takes here: one route prefix on the site's host, deployed by a dispatched
workflow, with no dependency and its own tests.

## Decision

1. **A second Worker, `workers/deadline-push`, at `/api/v1/push/*` on the site's host.** It is
   separate from the forwarder: the forwarder reads FPL and keeps nothing; this Worker keeps
   subscriptions and reads nothing of FPL. Each stays small and its deploy stays its own
   (`.github/workflows/deploy-deadline-push.yml`, dispatched from the default branch).
2. **The subscription is the only record.** A browser that turns the reminder on sends its Push
   API subscription (`endpoint`, `p256dh`, `auth`), the language and the page to open
   (`league_id`, `entry_id`), as [`push_subscription_v1`](../../contracts/push_subscription_v1.md).
   That row, keyed by the endpoint's hash, lives in a D1 database (`squadopt-push`). No name, no
   address, no device id, no visit log. Turning the reminder off deletes the row; a push service
   that answers 404 or 410 deletes it too.
3. **One notification per gameweek, three hours before its deadline.** A cron runs every
   quarter hour, reads the site's own `/data/fixtures.json` (the calendar the pages show, never
   FPL's bootstrap, as ADR 0012 decided), and when a deadline is ahead by three hours or less
   sends each subscriber not yet reminded of that week one message: "GW11: son 3 saat / Planın
   hazır." in the subscriber's language, opening their own page. A run between deadlines reads
   one small document and sends nothing. The message is held by the push service for at most
   three hours, so a device that comes online after the deadline gets nothing.
4. **The protocol is implemented on WebCrypto, with no dependency.** VAPID (RFC 8292) signs a
   JWT per push service with a P-256 key; the message is encrypted as RFC 8291's `aes128gcm`.
   The tests decrypt what the Worker encrypts and verify what it signs, so the implementation is
   held by the receiving side, not by a library's word.
5. **The VAPID private key is a secret of the `cloudflare-workers` environment**, written to the
   Worker by the deploy workflow; the public key is in `wrangler.toml` and answered by
   `GET /api/v1/push/key`, where every page reads it. Rotating the key replaces the environment
   secret and redeploys; existing subscriptions then need the page to subscribe again.
6. **On the page: one control, no sentence.** The sidebar's identity block carries a button
   beside Değiştir: "Hatırlat" off, "Hatırlatma açık" on, pressed state, nothing else. The
   control is drawn only where the browser can do it (service worker and Push API present, and
   the permission not denied). The service worker (`web/public/sw.js`) does one thing: show the
   notification and open the page on a tap. It caches nothing and is registered only when the
   member turns the reminder on, so a visitor who never does gets the static site unchanged.

## Consequences

- A member gets one notification a week, at a fixed distance from the deadline, and nothing
  else from this Worker. Changing the distance is a constant (`REMIND_BEFORE_MS`).
- The Worker depends on the site's calendar being published; a week the calendar does not state
  is a week nobody is reminded of. The run logs its counts, never an endpoint.
- D1's free tier (100 000 writes a day) is far above a subscription per visitor; the Workers KV
  limit that the forwarder's logs showed being hit (1 000 writes a day) is why KV was not used.
- Deleting the Worker (the workflow's `delete` action) stops the reminders and keeps the
  database; dropping the rows is a separate decision.
- Safari on iOS shows web notifications only for a site added to the home screen; the control
  is hidden where `PushManager` is absent, so those visitors see no promise the site cannot keep.
