import ledgerDocument from "../../public/data/2026-27/ledger.json" with { type: "json" };

import type { LedgerRowView, LedgerView } from "../data/schema";

/**
 * Ledger fixtures for the season-standing card.
 *
 * The committed `ledger.json` is the real published document and every realized field in it is
 * `null` — gameweek one had not settled when it was generated. That makes it the right fixture
 * for the "nothing to show yet" case and useless for every other one, so the settled shapes are
 * built from it rather than hand-written, keeping the unrelated fields honest.
 */
const rawView = ledgerDocument.payload as unknown as LedgerView;

/** The published document as it stands before any gameweek settles. */
export const unsettledLedgerFixture: LedgerView = rawView;

function row(overrides: Partial<LedgerRowView> & { gameweek: number }): LedgerRowView {
  const base = rawView.rows[0];
  return { ...base, ...overrides };
}

/** One settled gameweek, no transfer hits: net and gross agree. */
export const settledLedgerFixture: LedgerView = {
  ...rawView,
  settled_gameweeks: 1,
  total_projected_score: 56.0775,
  total_projected_score_settled: 56.0775,
  total_realized_score: 61,
  total_realized_net_score: 61,
  total_projection_error: 4.9225,
  total_transfer_hit_points: 0,
  rows: [
    row({
      gameweek: 1,
      settled: true,
      projected_score: 56.0775,
      realized_score: 61,
      realized_net_score: 61,
      projection_error: 4.9225,
      cumulative_projected_score: 56.0775,
      cumulative_realized_score: 61,
      transfer_hit_points: 0,
    }),
  ],
};

/**
 * Two settled gameweeks where the second took a four-point hit, so the season net is four
 * below the season gross. A card that shows gross here is showing a number FPL does not.
 */
export const hitLedgerFixture: LedgerView = {
  ...rawView,
  decided_gameweeks: 2,
  settled_gameweeks: 2,
  total_projected_score: 110.0775,
  total_projected_score_settled: 110.0775,
  total_realized_score: 111,
  total_realized_net_score: 107,
  total_projection_error: 0.9225,
  total_transfer_hit_points: 4,
  rows: [
    row({
      gameweek: 1,
      settled: true,
      projected_score: 56.0775,
      realized_score: 61,
      realized_net_score: 61,
      projection_error: 4.9225,
      cumulative_projected_score: 56.0775,
      cumulative_realized_score: 61,
      transfer_hit_points: 0,
    }),
    row({
      gameweek: 2,
      decision_kind: "transfer",
      settled: true,
      projected_score: 54,
      realized_score: 50,
      realized_net_score: 46,
      projection_error: -4,
      cumulative_projected_score: 110.0775,
      cumulative_realized_score: 111,
      transfer_count: 2,
      transfer_hit_points: 4,
    }),
  ],
};

/**
 * A third gameweek is decided but not settled. The card must report gameweek two — the latest
 * week with an outcome — rather than the latest row.
 */
export const pendingWeekLedgerFixture: LedgerView = {
  ...hitLedgerFixture,
  decided_gameweeks: 3,
  rows: [
    ...hitLedgerFixture.rows,
    row({
      gameweek: 3,
      decision_kind: "transfer",
      settled: false,
      projected_score: 58,
      realized_score: null,
      realized_net_score: null,
      projection_error: null,
      cumulative_projected_score: 168.0775,
      cumulative_realized_score: null,
      transfer_hit_points: 0,
    }),
  ],
};
