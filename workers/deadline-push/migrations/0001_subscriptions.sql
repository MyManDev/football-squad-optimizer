-- One browser's push subscription: the endpoint and keys the Push API gives, the language and
-- the page a tap opens, and the last gameweek it was reminded of. Nothing else of the visitor.
CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  endpoint TEXT NOT NULL UNIQUE,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  language TEXT NOT NULL,
  league_id INTEGER NOT NULL,
  entry_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  last_sent_gameweek INTEGER
);

CREATE INDEX IF NOT EXISTS subscriptions_due ON subscriptions (last_sent_gameweek, created_at);
