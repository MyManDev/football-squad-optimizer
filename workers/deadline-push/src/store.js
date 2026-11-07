// Where the subscriptions live: a D1 database in production, a Map in the tests. Both keep
// the same four operations, so worker.js never speaks SQL and the tests never need D1.
//
// A row is one browser's push subscription: its endpoint and the two keys the Push API gives,
// the language and the page to open, and the last gameweek it was reminded of. Nothing else
// about the visitor is kept (docs/architecture/decisions/0013-deadline-reminders.md).

/** The row's id: the endpoint's SHA-256 as hex, so one endpoint is one row however often it is sent. */
export async function subscriptionId(endpoint) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** The store over a D1 binding. */
export function d1Store(db) {
  return {
    async upsert(subscription, nowIso) {
      const id = await subscriptionId(subscription.endpoint);
      await db
        .prepare(
          `INSERT INTO subscriptions (id, endpoint, p256dh, auth, language, league_id, entry_id, created_at)
           VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
           ON CONFLICT(id) DO UPDATE SET
             p256dh = excluded.p256dh, auth = excluded.auth, language = excluded.language,
             league_id = excluded.league_id, entry_id = excluded.entry_id`,
        )
        .bind(
          id,
          subscription.endpoint,
          subscription.p256dh,
          subscription.auth,
          subscription.language,
          subscription.league_id,
          subscription.entry_id,
          nowIso,
        )
        .run();
    },
    async remove(endpoint) {
      const id = await subscriptionId(endpoint);
      const result = await db.prepare("DELETE FROM subscriptions WHERE id = ?1").bind(id).run();
      return (result.meta?.changes ?? 0) > 0;
    },
    /** The rows not yet reminded of `gameweek`, oldest first, at most `limit`. */
    async due(gameweek, limit) {
      const { results } = await db
        .prepare(
          `SELECT id, endpoint, p256dh, auth, language, league_id, entry_id
           FROM subscriptions
           WHERE last_sent_gameweek IS NULL OR last_sent_gameweek < ?1
           ORDER BY created_at
           LIMIT ?2`,
        )
        .bind(gameweek, limit)
        .all();
      return results ?? [];
    },
    async markSent(id, gameweek) {
      await db
        .prepare("UPDATE subscriptions SET last_sent_gameweek = ?2 WHERE id = ?1")
        .bind(id, gameweek)
        .run();
    },
    async removeById(id) {
      await db.prepare("DELETE FROM subscriptions WHERE id = ?1").bind(id).run();
    },
    async count() {
      const row = await db.prepare("SELECT COUNT(*) AS n FROM subscriptions").first();
      return row?.n ?? 0;
    },
  };
}

/** The same store in memory, for the tests. */
export function memoryStore() {
  const rows = new Map();
  return {
    rows,
    async upsert(subscription, nowIso) {
      const id = await subscriptionId(subscription.endpoint);
      const before = rows.get(id);
      rows.set(id, {
        id,
        ...subscription,
        created_at: before?.created_at ?? nowIso,
        last_sent_gameweek: before?.last_sent_gameweek ?? null,
      });
    },
    async remove(endpoint) {
      return rows.delete(await subscriptionId(endpoint));
    },
    async due(gameweek, limit) {
      return [...rows.values()]
        .filter((row) => row.last_sent_gameweek === null || row.last_sent_gameweek < gameweek)
        .sort((a, b) => a.created_at.localeCompare(b.created_at))
        .slice(0, limit)
        .map(({ created_at, last_sent_gameweek, ...row }) => row);
    },
    async markSent(id, gameweek) {
      const row = rows.get(id);
      if (row) row.last_sent_gameweek = gameweek;
    },
    async removeById(id) {
      rows.delete(id);
    },
    async count() {
      return rows.size;
    },
  };
}
