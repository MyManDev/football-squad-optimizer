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
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";
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

/** How the next worker answers: the real solve, or a run that ends without a plan. */
let workerAnswer: "solve" | "failed" | "refused" = "solve";

/** How many times the page asked the unreachable service what it computes. */
let capabilityReads = 0;

/** The worker the page creates, answered in process by the real solver. */
class InProcessWorker {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  postMessage(request: DevicePlanRequest): void {
    let reply: DevicePlanReply;
    try {
      if (workerAnswer === "failed") throw new Error("The solver could not load here.");
      if (workerAnswer === "refused") throw new DevicePlanRefused("infeasible", "plan");
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
  workerAnswer = "solve";
  capabilityReads = 0;
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
    capabilityReads += 1;
    throw new Error("The compute service could not be reached.");
  }
}

interface PageOptions {
  service?: "static" | "unreachable";
  /** The other members' documents: read at once, held until a promise settles, or unreadable. */
  rivals?: "read" | Promise<void> | "unreadable";
  /** The shared device document: published, absent, or from another capture. */
  devicePlan?: "published" | "missing" | "other-capture";
}

function renderPage(search: string, options: PageOptions | PageOptions["service"] = {}) {
  const {
    service = "static",
    rivals = "read",
    devicePlan = "published",
  } = typeof options === "string" ? { service: options } : options;
  const documents = squads();
  stubTree({
    entrySquad: vi.fn<LeagueTree["entrySquad"]>().mockImplementation(async (id) => {
      if (id !== ENTRY && rivals === "unreadable")
        throw new LeagueDataError(`entries/${id}.json did not answer.`);
      if (id !== ENTRY && rivals instanceof Promise) await rivals;
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
    devicePlan: vi.fn<LeagueTree["devicePlan"]>().mockImplementation(async () => {
      if (devicePlan === "missing") throw new LeagueDataMissing("device-plan.json");
      return {
        contract_version: "provisional_league_ui_v1",
        generated_at_utc: "2026-10-03T00:00:00Z",
        source_kind: "live",
        payload:
          devicePlan === "other-capture"
            ? { ...document, source_snapshot_id: "fpl-live-another-capture" }
            : document,
      };
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
      // The plan is on the page; the offer to compute it here has done its work.
      expect(container).not.toHaveTextContent(computeCopy.serviceUnreachableDevice);
    },
    60_000,
  );

  it.each([
    { ending: "failed", service: "unreachable" },
    { ending: "refused", service: "unreachable" },
    { ending: "unpublished", service: "unreachable" },
    { ending: "other-capture", service: "unreachable" },
    { ending: "failed", service: "static" },
  ] as const)(
    "stops offering the device once a run ends without a plan ($ending, service $service)",
    async ({ ending, service }) => {
      if (ending === "failed" || ending === "refused") workerAnswer = ending;
      const { container } = renderPage(`mode=fark-yarat&window=1&rival=${RIVAL}`, {
        service,
        devicePlan:
          ending === "unpublished"
            ? "missing"
            : ending === "other-capture"
              ? "other-capture"
              : "published",
      });
      await waitFor(() => expect(deviceButton()).not.toBeNull());
      if (service === "unreachable")
        await waitFor(() =>
          expect(container).toHaveTextContent(computeCopy.serviceUnreachableDevice),
        );
      await act(async () => deviceButton()!.click());
      await waitFor(() =>
        expect(container.querySelector(`[data-device-state='${ending}']`)).not.toBeNull(),
      );
      expect(container).not.toHaveTextContent(computeCopy.serviceUnreachableDevice);
      if (service === "unreachable")
        expect(container).toHaveTextContent(computeCopy.serviceUnreachableAbsent);
      // The decision area says what is published for this selection; it is not left empty.
      const decision = screen.getByRole("region", { name: copy.decisionTitle });
      expect(decision).toHaveTextContent(copy.publicationStates["not-listed"].title);
    },
    60_000,
  );

  it("never offers a rival whose captain is not in their eleven", async () => {
    renderPage(`mode=ortak-koru&window=1&rival=${RIVAL}`);
    await waitFor(() => expect(deviceButton()).not.toBeNull());
    expect(offeredRivals()).toContain(RIVAL);
    expect(offeredRivals()).not.toContain(BENCHED_CAPTAIN);
    cleanup();

    // Named in the link, he is still not the rival once the documents are read: the device
    // has nothing to offer.
    const { container } = renderPage(`mode=ortak-koru&window=1&rival=${BENCHED_CAPTAIN}`);
    await waitFor(() => {
      expect(offeredRivals()).toContain(RIVAL);
      expect(offeredRivals()).not.toContain(BENCHED_CAPTAIN);
    });
    expect(deviceButton()).toBeNull();
    expect(container).not.toHaveTextContent(copy.deviceRefused);
  }, 60_000);

  it("keeps the link's rival and reads as loading until the rivals' documents are read", async () => {
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    const { container } = renderPage(`mode=ortak-koru&window=1&rival=${RIVAL}`, {
      service: "unreachable",
      rivals: held,
    });
    await screen.findByText(copy.loadingRivals);
    // The service has answered (unreachable) before anything is checked.
    await waitFor(() => expect(capabilityReads).toBeGreaterThan(0));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.getByText(copy.loadingRivals)).toBeVisible();
    const summary = screen.getByTestId("member-selection-summary");
    expect(summary).toHaveTextContent(copy.rivalLabel);
    expect(offeredRivals()).toContain(RIVAL);
    const whileReading = [
      copy.publicationStates["not-listed"].title,
      copy.computeUnsupportedSelection,
      computeCopy.serviceUnreachableAbsent,
      computeCopy.serviceUnreachable,
      copy.rivalNone,
    ];
    for (const sentence of whileReading) expect(container).not.toHaveTextContent(sentence);
    expect(deviceButton()).toBeNull();

    await act(async () => release());
    await waitFor(() => expect(deviceButton()).not.toBeNull());
    expect(screen.queryByText(copy.loadingRivals)).toBeNull();
    expect(summary).toHaveTextContent(copy.rivalLabel);
    for (const sentence of whileReading) expect(container).not.toHaveTextContent(sentence);
  }, 60_000);

  it("never calls the squads unpublished when their reads failed", async () => {
    const { container } = renderPage(`mode=ortak-koru&window=1&rival=${RIVAL}`, {
      rivals: "unreadable",
    });
    await screen.findByText(copy.rivalsUnreadable);
    // The link's rival stays the choice; the device cannot use a rival it could not read.
    expect(offeredRivals()).toContain(RIVAL);
    expect(screen.getByTestId("member-selection-summary")).toHaveTextContent(copy.rivalLabel);
    expect(container).not.toHaveTextContent(copy.rivalNone);
    expect(deviceButton()).toBeNull();
    cleanup();

    const { container: none } = renderPage("mode=ortak-koru&window=1", { rivals: "unreadable" });
    await screen.findByText(copy.rivalsUnreadable);
    expect(none).not.toHaveTextContent(copy.rivalNone);
  }, 60_000);
});
