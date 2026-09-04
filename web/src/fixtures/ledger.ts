import ledgerDocument from "../../public/data/2026-27/ledger.json" with { type: "json" };

import type { LedgerRowView, LedgerView } from "../data/schema";

/**
 * Ledger fixtures for the season-standing card.
 *
 * Shapes are built from the committed `ledger.json` rather than hand-written, so the fields
 * these tests do not care about stay whatever the real document says.
 *
 * The unsettled one used to *be* that document, on the reasoning that every realized field in
 * it was `null`. That reasoning had an expiry date nobody noticed: settling gameweek one
 * republished the file with `settled_gameweeks: 1`, and the fixture named "unsettled" quietly
 * became settled, failing the test that asserts the card stays away until there is something
 * to show. A fixture whose meaning depends on the state of live data is a fixture that changes
 * meaning without an edit, so the unsettled case is now emptied explicitly.
 */
const rawView = ledgerDocument.payload as unknown as LedgerView;

/** A season with nothing settled yet: the card must not appear at all. */
export const unsettledLedgerFixture: LedgerView = {
  ...rawView,
  settled_gameweeks: 0,
  total_projected_score_settled: 0,
  total_realized_score: null,
  total_realized_net_score: null,
  total_projection_error: null,
  total_transfer_hit_points: 0,
  rows: rawView.rows.map((entry) => ({
    ...entry,
    settled: false,
    realized_score: null,
    realized_net_score: null,
    projection_error: null,
    cumulative_realized_score: null,
    transfer_hit_points: 0,
  })),
};

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
