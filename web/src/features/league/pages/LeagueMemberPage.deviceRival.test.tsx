/**
 * A rival strategy the member's device solves, on the whole page, from a publish that lists
 * only the pure-points plan (as the live tree does): the rival the device plays against is
 * the rival whose squad the page reads, so the card compares the two by name; nothing on
 * the page calls the selection unlisted or unsupported while the device can answer it; and
 * a rival the device could not use (a captain on the bench) is never offered.
 */

/// <reference types="node" />
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { notFound } from "../../../testSupport/fetchByUrl";
import { stubTree, withLeague } from "../../../testSupport/league";
import * as clients from "../advice/adviceClient";
import { COMPUTE_COPY } from "../advice/computeCopy";
import type { LeagueTree } from "../data";
import { LeagueDataMissing } from "../dataErrors";
import type { LpSolver } from "../device/lp/problem";
import { solveRequest, type DevicePlanRequest } from "../device/requests";
import type { DevicePlanReply } from "../device/deviceSolver.worker";
import { DevicePlanRefused } from "../device/solve/week";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { EntryAdviceIndex, EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage } from "./LeagueMemberPage";

const require = createRequire(import.meta.url);
let highs: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  highs = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

/** The worker the page creates, answered in process by the real solver. */
class InProcessWorker {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  postMessage(request: DevicePlanRequest): void {
    let reply: DevicePlanReply;
    try {
      reply = { id: request.id, kind: "answer", answer: solveRequest(highs, request, () => 0) };
    } catch (error) {
      reply =
        error instanceof DevicePlanRefused
          ? { id: request.id, kind: "refused", status: error.status, stage: error.stage }
          : { id: request.id, kind: "failed" };
    }
    queueMicrotask(() => {
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>);
      this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
    });
  }
  terminate(): void {}
}

beforeEach(() => {
  vi.stubGlobal("Worker", InProcessWorker);
  // Nothing leaves the test: the fixture calendar and anything else unstubbed is absent.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => notFound()),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const world = fixture.rivals;
const document = world.document as unknown as DevicePlanDocument;
const SNAPSHOT = document.source_snapshot_id;
const ENTRY = 35249001;
const RIVAL = 35249002;
/** A member whose captain sits on the bench, as entry 5349883 does on the live tree. */
const BENCHED_CAPTAIN = 35249003;
const copy = MESSAGES.tr.leagueMembers;
const computeCopy = COMPUTE_COPY.tr;

function live(envelope: LeagueViewEnvelope<EntrySquad>, payload: Partial<EntrySquad> = {}) {
  return {
    ...envelope,
    source_kind: "live" as const,
    payload: { ...envelope.payload, source_snapshot_id: SNAPSHOT, ...payload },
  };
}

/** The rival's eleven as the device fixture names it, in the rival document's player shape. */
function rivalSquad(): LeagueViewEnvelope<EntrySquad> {
  const base = mockEntrySquadEnvelopes[RIVAL]!;
  const eleven = world.rivals["202"]!;
  const players = new Map(document.players.map((p) => [p.id, p]));
  return live(base, {
    starting_xi: eleven.starting_xi.map((id, index) => ({
      ...base.payload.starting_xi[index]!,
      player_id: id,
      name: players.get(id)!.name,
      short_name: players.get(id)!.short_name,
      position: players.get(id)!.position as EntrySquad["starting_xi"][number]["position"],
      team: players.get(id)!.team,
      is_captain: id === eleven.captain,
      is_vice_captain: false,
    })),
  });
}

function benchedCaptain(): LeagueViewEnvelope<EntrySquad> {
  const base = mockEntrySquadEnvelopes[BENCHED_CAPTAIN]!;
  return live(base, {
    starting_xi: base.payload.starting_xi.map((p) => ({ ...p, is_captain: false })),
    bench: base.payload.bench.map((p, index) => ({ ...p, is_captain: index === 2 })),
  });
}

function squads(): Record<number, LeagueViewEnvelope<EntrySquad>> {
  const all: Record<number, LeagueViewEnvelope<EntrySquad>> = {};
  for (const [id, envelope] of Object.entries(mockEntrySquadEnvelopes))
    all[Number(id)] = live(envelope);
  all[ENTRY] = live(mockEntrySquadEnvelopes[ENTRY]!, {
    device_plan: world.members["101"] as unknown as DevicePlanEntry,
  });
  all[RIVAL] = rivalSquad();
  all[BENCHED_CAPTAIN] = benchedCaptain();
  return all;
}

/** The member's index as the live tree publishes it: the pure-points plan, no rival pairs. */
function liveIndex(): LeagueViewEnvelope<EntryAdviceIndex> {
  const index = mockEntryAdviceIndex(ENTRY);
  return {
    ...index,
    payload: {
      ...index.payload,
      windows: { "saf-puan": [1] },
      strategies: ["saf-puan"],
      rival_entry_ids: [],
      default_rival_entry_id: null,
      suggested_strategy: null,
      computed: [],
      unavailable: [],
    },
  };
}

class UnreachableClient extends clients.StaticOnlyAdviceClient {
  async readCapabilities(): Promise<null> {
    throw new Error("The compute service could not be reached.");
  }
}

function renderPage(search: string, service: "static" | "unreachable" = "static") {
  const documents = squads();
  stubTree({
    entrySquad: vi.fn<LeagueTree["entrySquad"]>().mockImplementation(async (id) => {
      const found = documents[id];
      if (!found) throw new LeagueDataMissing(`entries/${id}.json`);
      return found;
    }),
    members: vi.fn<LeagueTree["members"]>().mockResolvedValue(mockLeagueMembersEnvelope),
    entryAdviceIndex: vi.fn<LeagueTree["entryAdviceIndex"]>().mockResolvedValue(liveIndex()),
    entryAdvice: vi
      .fn<LeagueTree["entryAdvice"]>()
      .mockImplementation(async (id, mode, window, other) =>
        mockEntryAdviceEnvelope(id, mode, window, other),
      ),
    devicePlan: vi.fn<LeagueTree["devicePlan"]>().mockResolvedValue({
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: "2026-10-03T00:00:00Z",
      source_kind: "live",
      payload: document,
    }),
  });
  if (service === "unreachable") {
    vi.spyOn(clients, "createAdviceClient").mockImplementation(
      (loader) => new UnreachableClient(loader),
    );
  }
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={queries}>
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?${search}`]}>
          {withLeague(
            <Routes>
              <Route path="/league/:leagueId/members/:entryId" element={<LeagueMemberPage />} />
            </Routes>,
          )}
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const deviceButton = () => screen.queryByRole("button", { name: copy.deviceButton });

/** The rivals the plan controls list, by entry id; none while the control is not drawn. */
function offeredRivals(): number[] {
  const select = screen.queryByText(copy.rivalLabel)?.closest("label")?.querySelector("select");
  return select ? [...select.options].map((option) => Number(option.value)) : [];
}

describe("a rival strategy solved on the member's device", () => {
  it("compares the plan with the rival's squad by name", async () => {
    const { container } = renderPage(`mode=ortak-koru&window=1&rival=${RIVAL}`);
    await waitFor(() => expect(deviceButton()).not.toBeNull());
    await act(async () => deviceButton()!.click());
    await waitFor(
      () => expect(container.querySelector("[data-device-state='done']")).not.toBeNull(),
      { timeout: 30_000 },
    );
    const section = await screen.findByRole("region", { name: copy.rivalPlayersTitle });
    expect(section).not.toHaveTextContent(copy.rivalPlayersUnavailable);
    expect(within(section).getByText(copy.rivalPlayerGroups.shared)).toBeVisible();
    expect(within(section).getByText(copy.rivalPlayerGroups.rivalOnly)).toBeVisible();
  }, 60_000);

  it.each(["static", "unreachable"] as const)(
    "is offered plainly, never as unlisted or unsupported (service %s)",
    async (service) => {
      const { container } = renderPage(`mode=fark-yarat&window=1&rival=${RIVAL}`, service);
      await waitFor(() => expect(deviceButton()).not.toBeNull());
      if (service === "unreachable")
        await waitFor(() =>
          expect(container).toHaveTextContent(computeCopy.serviceUnreachableDevice),
        );
      const contradictions = [
        copy.publicationStates["not-listed"].title,
        copy.publicationStates["not-listed"].body,
        copy.computeUnsupportedSelection,
        computeCopy.serviceUnreachableAbsent,
        computeCopy.notComputable,
      ];
      for (const sentence of contradictions) expect(container).not.toHaveTextContent(sentence);

      await act(async () => deviceButton()!.click());
      await waitFor(
        () => expect(container.querySelector("[data-device-state='done']")).not.toBeNull(),
        { timeout: 30_000 },
      );
      for (const sentence of contradictions) expect(container).not.toHaveTextContent(sentence);
    },
    60_000,
  );

  it("never offers a rival whose captain is not in their eleven", async () => {
    renderPage(`mode=ortak-koru&window=1&rival=${RIVAL}`);
    await waitFor(() => expect(deviceButton()).not.toBeNull());
    expect(offeredRivals()).toContain(RIVAL);
    expect(offeredRivals()).not.toContain(BENCHED_CAPTAIN);
    cleanup();

    // Named in the link, he is still not the rival: the device has nothing to offer.
    const { container } = renderPage(`mode=ortak-koru&window=1&rival=${BENCHED_CAPTAIN}`);
    await waitFor(() => expect(offeredRivals()).toContain(RIVAL));
    expect(offeredRivals()).not.toContain(BENCHED_CAPTAIN);
    expect(deviceButton()).toBeNull();
    expect(container).not.toHaveTextContent(copy.deviceRefused);
  }, 60_000);
});
