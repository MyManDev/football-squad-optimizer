/** The horizon request, worker reply, hook and existing service-window presentation. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import fixture from "../../../fixtures/device-plan/horizons.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { withLeague } from "../../../testSupport/league";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import type { LpSolver } from "./lp/problem";
import { replyTo, type DevicePlanReply } from "./replies";
import { solveRequest } from "./requests";
import type { DevicePlanDocument } from "./types";
import { useDevicePlan, type DeviceSolver } from "./useDevicePlan";

const require = createRequire(import.meta.url);
const document = fixture.document as unknown as DevicePlanDocument;
const ENTRY = 35249001;
let highs: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  highs = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);
afterEach(cleanup);

function sameFields(actual: unknown, expected: unknown) {
  if (typeof expected === "number") {
    expect(typeof actual).toBe("number");
    expect(Math.abs((actual as number) - expected)).toBeLessThanOrEqual(1e-6);
  } else if (Array.isArray(expected)) {
    expect(Array.isArray(actual)).toBe(true);
    expect(actual).toHaveLength(expected.length);
    expected.forEach((value, index) => sameFields((actual as unknown[])[index], value));
  } else if (expected !== null && typeof expected === "object") {
    expect(actual).not.toBeNull();
    for (const [key, value] of Object.entries(expected))
      sameFields((actual as Record<string, unknown>)[key], value);
  } else expect(actual).toEqual(expected);
}

describe.each(fixture.members)("member $entry_id presentation", (member) => {
  it.each([3, 5] as const)(
    "matches the service's H%i fields",
    (window) => {
      const answer = solveRequest(highs, { document, entry: member.entry, window });
      const squad = {
        ...mockEntrySquadEnvelopes[ENTRY]!.payload,
        entry: { ...mockEntrySquadEnvelopes[ENTRY]!.payload.entry, entry_id: member.entry_id },
        purchase_prices_known: true,
        free_transfers_known: true,
      };
      const payload = deviceAdviceEnvelope(
        document,
        squad,
        answer,
        new Date("2026-09-02T10:00:00Z"),
        9,
      ).payload;
      const expected = member.reference[String(window) as "3" | "5"].presentation;
      sameFields(payload, expected);
      // A plain service window does not add a lineup section for every future week.
      expect(payload.plan_weeks?.every((week) => week.lineup === undefined)).toBe(true);
    },
    60_000,
  );
});

it("posts one final horizon answer without solving chip gains", () => {
  const replies: DevicePlanReply[] = [];
  replyTo(highs, { id: 7, document, entry: fixture.members[1]!.entry, window: 5 }, (reply) =>
    replies.push(reply),
  );
  expect(replies).toHaveLength(1);
  expect(replies[0]).toMatchObject({ id: 7, kind: "answer", answer: { window: 5 } });
});

it("refuses unverified combinations before invoking the solver", () => {
  const solve = vi.fn();
  const solver = { solve } as unknown as LpSolver;
  const request = { document, entry: fixture.members[0]!.entry, window: 3 as const };
  for (const extra of [
    { chip: "3xc" as const },
    { top100Weight: 20 },
    { chipGains: ["3xc" as const] },
    { alternatives: true },
    {
      strategy: {
        name: "ortak-koru" as const,
        rival: {
          entry_id: 2,
          starting_xi: request.entry.held.slice(0, 11),
          captain: request.entry.held[0]!,
        },
      },
    },
  ])
    expect(() => solveRequest(solver, { ...request, ...extra })).toThrow(
      "unsupported horizon selection",
    );
  expect(solve).not.toHaveBeenCalled();
});

it.each([3, 5] as const)(
  "leaves slow H%i to the service without loading a worker",
  async (window) => {
    const member = fixture.members[1]!;
    const squad = {
      ...mockEntrySquadEnvelopes[ENTRY]!.payload,
      source_snapshot_id: document.source_snapshot_id,
      device_plan: member.entry,
    };
    const loadDocument = vi.fn(async () => ({
      contract_version: "provisional_league_ui_v1" as const,
      generated_at_utc: "2026-09-02T10:00:00Z",
      source_kind: "live" as const,
      payload: document,
    }));
    const createSolver = vi.fn(
      () =>
        ({
          onmessage: null,
          postMessage: vi.fn(),
          terminate: vi.fn(),
        }) satisfies DeviceSolver,
    );
    function Harness() {
      const device = useDevicePlan(
        squad,
        { leagueId: squad.league_id, entryId: ENTRY, strategy: "saf-puan", window },
        { loadDocument, createSolver },
      );
      return (
        <>
          <button onClick={device.run}>run</button>
          <output data-testid="available">{String(device.available)}</output>
          <output data-testid="phase">{device.state.phase}</output>
        </>
      );
    }
    render(withLeague(<Harness />));
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("available")).toHaveTextContent("false"));
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(loadDocument).not.toHaveBeenCalled();
    expect(createSolver).not.toHaveBeenCalled();
  },
);
