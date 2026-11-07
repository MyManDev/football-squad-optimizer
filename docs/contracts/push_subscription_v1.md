# `push_subscription_v1`: a browser asks to be reminded before each deadline

The request a page sends, with `PUT /api/v1/push/subscriptions` on the site's host, when a
member turns the reminder on; the same endpoint with `DELETE` and `{"endpoint": ...}` turns it
off. The deadline reminder Worker ([ADR 0013](../architecture/decisions/0013-deadline-reminders.md))
keeps the request as one row and, when a gameweek's deadline is three hours away, sends that
browser one notification for that week. The schema is closed; the examples are synthetic.

| Field | Meaning |
| --- | --- |
| `endpoint` | The push service address the browser's `PushSubscription` carries; https only, at most 2048 characters. |
| `keys.p256dh`, `keys.auth` | The subscription's public key and authentication secret, base64url as the Push API gives them. The Worker encrypts each message with them (RFC 8291) and never reads a notification itself. |
| `language` | `tr` or `en`: the language the notification speaks. |
| `league_id` | The league the member's page is under; `0` for a team opened on its own (`/entry/<id>`). |
| `entry_id` | The member's FPL team number. With `league_id` it names the page a tap on the notification opens. |

The Worker answers `204` when the row is kept or dropped, `400` with `{"error": <reason>}` for a
request it cannot read, `405` for another method and `503` when its store is away. One endpoint
is one row: a second request for the same endpoint replaces the language and the page, and
the row's "last reminded" week is kept.

`GET /api/v1/push/key` answers `{"contract_version": "push_key_v1", "public_key": <base64url
P-256 point>}`: the VAPID public key a page passes to `pushManager.subscribe`.

Held by `workers/deadline-push/test/rules.test.mjs`, which checks the examples against the
schema and reads each through the Worker's own reader.
