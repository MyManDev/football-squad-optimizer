import { describe, expect, it } from "vitest";
import vectors from "./vectors.json";
import { EntryStateError, planGameweek, readEntry, readHistory, readPicks } from "./parsers";
import { bankedFreeTransfers, chipStates, heldSquadBasis, type ChipWindow } from "./rules";

describe("the production Python entry-state vectors", () => {
  for (const row of vectors.banking)
    it(row.name, () => {
      expect(
        bankedFreeTransfers(
          readHistory(row.history, vectors.entry_id),
          row.week,
          row.cap,
          row.active_chip,
        ),
      ).toEqual(row.expected);
    });
  for (const row of vectors.picks)
    it(row.name, () => {
      const read = () => readPicks(row.input, vectors.entry_id, 4);
      if ("refused" in row.expected) expect(read).toThrow(EntryStateError);
      else expect(read()).toEqual(row.expected);
    });
  for (const row of vectors.free_hits)
    it(row.name, () => {
      const read = (week: number) => readPicks(row.picks[week - 1], vectors.entry_id, week);
      const basis = () => heldSquadBasis(read(row.picks.length), read);
      if (row.expected_week === null) expect(basis).toThrow(EntryStateError);
      else expect(basis().gameweek).toBe(row.expected_week);
    });
  for (const row of vectors.chips)
    it(`chip states: ${row.name}`, () => {
      expect(chipStates(vectors.windows as ChipWindow[], row.week, row.played)).toEqual(
        row.expected,
      );
    });
  for (const row of vectors.deadlines)
    it(`deadline at ${row.as_of}`, () => {
      const read = () => planGameweek(vectors.bootstrap, row.as_of);
      if (row.expected_week === null) expect(read).toThrow(EntryStateError);
      else expect(read()).toBe(row.expected_week);
    });
});

it("reads only the named entry", () => {
  expect(readEntry({ id: 101, name: "Test squad", started_event: 3 }, 101)).toEqual({
    entry_id: 101,
    name: "Test squad",
    started_event: 3,
  });
  expect(() => readEntry({ id: 102, name: "Other", started_event: 3 }, 101)).toThrow(
    EntryStateError,
  );
});

it.each([
  null,
  [],
  "<html>error</html>",
  { current: [] },
  { current: [], chips: false },
  { current: [null], chips: [] },
])("refuses a malformed history: %j", (value) => {
  expect(() => readHistory(value, 101)).toThrow(EntryStateError);
});

it("refuses duplicate weeks and noninteger or negative transfer counts", () => {
  const row = { event: 1, event_transfers: 0, event_transfers_cost: 0 };
  expect(() => readHistory({ current: [row, row], chips: [] }, 101)).toThrow(EntryStateError);
  for (const count of [true, -1, 1.5, "1", Number.MAX_SAFE_INTEGER + 1])
    expect(() =>
      readHistory({ current: [{ ...row, event_transfers: count }], chips: [] }, 101),
    ).toThrow(EntryStateError);
});

it("does not treat an absent bank or unknown chip history as zero", () => {
  const row = { event: 1, event_transfers: 15, event_transfers_cost: 0, bank: null };
  expect(readHistory({ current: [row], chips: [] }, 101).weeks[1]?.bank).toBeNull();
  expect(() => readHistory({ current: [row] }, 101)).toThrow(EntryStateError);
  expect(chipStates(vectors.windows as ChipWindow[], 4, null).wildcard.first_half?.state).toBe(
    "unknown",
  );
});

it("preserves market value separately from any spendable selling budget", () => {
  const picks = readPicks(vectors.picks[0]!.input, 101, 4);
  expect(picks.market_value_tenths).toBe(1000);
  expect(picks.bank_tenths).toBe(10);
  expect(picks).not.toHaveProperty("sell_tenths");
  expect(picks).not.toHaveProperty("squad_sell_value_tenths");
});

it("refuses a wrong week, duplicate positions, bad armbands and a forged autosub", () => {
  const ordinary = vectors.picks[0]!.input;
  expect(() => readPicks(ordinary, 101, 3)).toThrow(EntryStateError);
  for (const change of [
    { position: 1 },
    { is_captain: true },
    { multiplier: 4 },
    { is_vice_captain: "true" },
  ]) {
    const value = structuredClone(ordinary);
    Object.assign(value.picks[1]!, change);
    expect(() => readPicks(value, 101, 4)).toThrow(EntryStateError);
  }
  const benched = structuredClone(vectors.picks[1]!.input);
  benched.automatic_subs[0]!.entry = 999;
  expect(() => readPicks(benched, 101, 4)).toThrow(EntryStateError);
});

it("never skips a missing Free Hit basis week or reads a different entry's squad", () => {
  const source = vectors.free_hits.find((row) => row.name === "consecutive-free-hits")!;
  const captured = readPicks(source.picks.at(-1), 101, 4);
  expect(() =>
    heldSquadBasis(captured, () => {
      throw new EntryStateError("Missing picks.");
    }),
  ).toThrow("Missing picks");
  expect(() =>
    heldSquadBasis(captured, (week) => readPicks(source.picks[week - 1], 999, week)),
  ).toThrow("identity mismatch");
});

it.each([
  "2026-02-30T12:00:00Z",
  "2026-08-01 12:00:00",
  "2026-08-01T24:00:00Z",
  "2026-08-01T12:00:00+24:00",
  "0000-01-01T12:00:00Z",
])("refuses invalid calendar or timezone input: %s", (asOf) => {
  expect(() => planGameweek(vectors.bootstrap, asOf)).toThrow(EntryStateError);
});

it("uses the instant rather than the timezone spelling or is_next flag", () => {
  expect(planGameweek(vectors.bootstrap, "2026-08-01T15:00:00+03:00")).toBe(2);
  expect(() =>
    planGameweek(
      { events: [vectors.bootstrap.events[0], vectors.bootstrap.events[0]] },
      "2026-07-01T00:00:00Z",
    ),
  ).toThrow(EntryStateError);
});

it("refuses a chip play outside every window or an unrepresentable window set", () => {
  expect(() => chipStates(vectors.windows as ChipWindow[], 4, { freehit: [1] })).toThrow(
    EntryStateError,
  );
  expect(() =>
    chipStates([...vectors.windows, vectors.windows[0]!] as ChipWindow[], 4, {}),
  ).toThrow(EntryStateError);
});
