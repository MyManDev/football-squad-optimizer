import { describe, expect, it } from "vitest";
import vectors from "./price-vectors.json";
import { EntryStateError, readHistory, readPicks } from "./parsers";
import {
  readElementPrices,
  readTransfers,
  rebuildPurchasePrices,
  sellingInputs,
  sellPriceTenths,
  type EntryTransfer,
  type PriceReplayInputs,
  type RebuiltPrices,
} from "./prices";

interface PriceVector {
  name: string;
  input: Omit<PriceReplayInputs, "transfers" | "history" | "opening" | "held"> & {
    transfers: (Omit<EntryTransfer, "time_utc"> & { entry: number; time: string })[];
    history: unknown;
    opening: unknown;
    held: { entry_history: { event: number } };
    current_prices: Readonly<Partial<Record<number, number>>>;
  };
  expected: Omit<RebuiltPrices, "reason">;
  expected_selling: ReturnType<typeof sellingInputs> | { refused: true };
}

// Keep JSON inference from expanding every deliberately malformed case into a large union.
const cases = vectors.cases as unknown as PriceVector[];

function replay(row: PriceVector) {
  const source = row.input;
  const held = readPicks(source.held, vectors.entry_id, source.held.entry_history.event);
  const result = rebuildPurchasePrices({
    ...source,
    transfers: readTransfers(source.transfers, vectors.entry_id),
    history: readHistory(source.history, vectors.entry_id),
    opening: readPicks(source.opening, vectors.entry_id, 1),
    held,
  });
  return { result, held };
}

describe("the production Python purchase-price vectors", () => {
  for (const row of cases)
    it(row.name, () => {
      const { result, held } = replay(row);
      const { reason: _reason, ...answer } = result;
      expect(answer).toEqual(row.expected);
      const sell = () =>
        sellingInputs(held, row.input.current_prices, result, row.input.sell_on_fee);
      if ("refused" in row.expected_selling) expect(sell).toThrow(EntryStateError);
      else expect(sell()).toEqual(row.expected_selling);
    });

  for (const sale of vectors.sales)
    it(`sells ${sale.purchase} at ${sale.current} with fee ${sale.fee}`, () => {
      expect(sellPriceTenths(sale.current, sale.purchase, sale.fee)).toBe(sale.expected);
    });
  for (const row of vectors.timestamps)
    it(`normalizes ${row.input[0]!.time} with microsecond precision`, () => {
      expect(readTransfers(row.input, vectors.entry_id)).toEqual(row.expected);
    });
});

it("reads and orders only the named entry's transfers", () => {
  const source = cases.find((row) => row.name === "sold-and-bought-back")!;
  expect(readTransfers(source.input.transfers, vectors.entry_id)).toEqual(vectors.parsed_transfers);
  expect(() => readTransfers(source.input.transfers, vectors.entry_id + 1)).toThrow(
    "entry mismatch",
  );
});

it("recognizes duplicate instants regardless of their timezone spelling", () => {
  const transfer = cases.find((row) => row.name === "one-purchase")!.input.transfers[0]!;
  expect(() =>
    readTransfers([transfer, { ...transfer, time: "2026-08-02T12:00:00+00:00" }], vectors.entry_id),
  ).toThrow("Duplicate transfer");
  expect(() =>
    readTransfers([{ ...transfer, time: "2026-08-02T15:00:00+03:00" }], vectors.entry_id),
  ).toThrow("expressed in UTC");
});

it.each([null, {}, [null], [{ entry: 101, event: 1, time: "not-a-date" }]])(
  "refuses a malformed transfer list: %j",
  (value) => {
    expect(() => readTransfers(value, vectors.entry_id)).toThrow(EntryStateError);
  },
);

it("refuses self-sales and noninteger or unsafe transfer prices", () => {
  const transfer = cases.find((row) => row.name === "one-purchase")!.input.transfers[0]!;
  for (const changes of [
    { element_in: transfer.element_out },
    { element_in_cost: 1.5 },
    { element_out_cost: Number.MAX_SAFE_INTEGER + 1 },
    { element_in_cost: -1 },
    { event: 39 },
  ])
    expect(() => readTransfers([{ ...transfer, ...changes }], vectors.entry_id)).toThrow(
      EntryStateError,
    );
});

it("derives opening prices from current prices and signed season changes", () => {
  expect(
    readElementPrices({
      elements: [
        { id: 1, now_cost: 65, cost_change_start: 5 },
        { id: 2, now_cost: 55, cost_change_start: -5 },
      ],
    }),
  ).toEqual({
    1: { current_tenths: 65, start_tenths: 60 },
    2: { current_tenths: 55, start_tenths: 60 },
  });
  const row = { id: 1, now_cost: 65, cost_change_start: 5 };
  for (const value of [
    { elements: [] },
    { elements: [row, row] },
    { elements: [{ ...row, cost_change_start: 66 }] },
    { elements: [{ ...row, cost_change_start: 0.5 }] },
    { elements: [{ ...row, now_cost: Number.MAX_SAFE_INTEGER, cost_change_start: -1 }] },
  ])
    expect(() => readElementPrices(value)).toThrow(EntryStateError);
});

it("keeps microsecond order and checks no sale at a different instant", () => {
  const row = cases.find((value) => value.name === "distinct-microseconds-are-not-tied")!;
  const transfers = readTransfers(row.input.transfers, vectors.entry_id);
  expect(transfers.map((transfer) => transfer.element_out)).toEqual([1, 16]);
  expect(replay(row).result).toMatchObject({ known: true, sales_checked: 0, prices: { 1: 70 } });
});

it("does not mutate held purchase prices while checking future or Free Hit transfers", () => {
  for (const name of ["pending-transfers", "free-hit-reverts", "active-free-hit"]) {
    const row = cases.find((value) => value.name === name)!;
    const before = structuredClone(row);
    const { result } = replay(row);
    expect(result).toMatchObject({ known: true, prices: { 1: 60 } });
    expect(result.prices).not.toHaveProperty("16");
    expect(row).toEqual(before);
  }
});

it("rejects unsafe selling totals and invalid fees", () => {
  const { result, held } = replay(cases[0]!);
  const high = Object.fromEntries(held.squad.map((id) => [id, Number.MAX_SAFE_INTEGER]));
  expect(() => sellingInputs(held, high, { ...result, prices: high }, 0.5)).toThrow(
    EntryStateError,
  );
  for (const fee of [-1, 1.01, NaN, Infinity])
    expect(() => sellPriceTenths(65, 60, fee)).toThrow(EntryStateError);
  expect(sellPriceTenths(Number.MAX_SAFE_INTEGER, 0, 0)).toBe(Number.MAX_SAFE_INTEGER);
});
