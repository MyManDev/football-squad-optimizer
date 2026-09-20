/**
 * The member page with a compute service configured.
 *
 * With the service's capabilities, a selection nobody published is offered to Hesapla
 * instead of ending in "not listed", the request carries the member's switches, the
 * computed plan is held to the squad's capture, and a wait survives a reload. A published
 * selection is still shown at once with no request. And a bundle built with an origin
 * whose service is down is the static site with one calm notice, never an error page.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceChipEnvelope,
  mockEntryAdviceIndex,
  mockEntryAdviceTop100Envelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestResult,
} from "../advice/adviceClient";
import { rememberJob } from "../advice/adviceJobStore";
import { AdviceApiError } from "../advice/adviceClient";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { TOP100_WEIGHTS } from "../advice/top100";
import * as data from "../data";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const INDEX = mockEntryAdviceIndex(ENTRY).payload;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const DEFAULT_RIVAL = INDEX.default_rival_entry_id!;
const OTHER_RIVAL = INDEX.rival_entry_ids.find(
  (id) => id !== DEFAULT_RIVAL && !INDEX.unavailable.some((row) => row.rival_entry_id === id),
)!;
const copy = MESSAGES.tr.leagueMembers;
// A heading only the advice card carries: the recommended lineup.
const PLAN_SHOWN = copy.lineupTitle;
const computeCopy = COMPUTE_COPY.tr;

const CAPABILITIES: AdviceCapabilities = {
  leagueId: INDEX.league_id,
  captureSnapshotId: SQUAD.payload.source_snapshot_id!,
  season: INDEX.season,
  gameweek: INDEX.gameweek,
  strategies: {
    "saf-puan": { windows: [1, 3, 5], requiresRival: false },
    "ortak-koru": { windows: [1, 3, 5], requiresRival: true },
    "fark-yarat": { windows: [1, 3, 5], requiresRival: true },
  },
  top100Weights: [...TOP100_WEIGHTS],
  managersWord: true,
};

class RecordingClient implements AdviceClient {
  requests: AdviceRequest[] = [];
  polls: string[] = [];
  answer: (request: AdviceRequest) => AdviceRequestResult;

  constructor(answer: (request: AdviceRequest) => AdviceRequestResult) {
    this.answer = answer;
  }

  async readAdvice(request: AdviceRequest): Promise<AdviceReadResult> {
    const outcome = this.answer(request);
    return outcome.kind === "advice" ? outcome : { kind: "not-computed" };
  }

  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    this.requests.push(request);
    return this.answer(request);
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    this.polls.push(jobId);
    return { jobId, status: "completed" };
  }
}

function computed(
  request: AdviceRequest,
  overrides: Partial<EntryAdvice> = {},
): LeagueViewEnvelope<EntryAdvice> {
  const base =
    (request.top100Weight ?? 0) !== 0
      ? mockEntryAdviceTop100Envelope(ENTRY, request.top100Weight!, false)
      : mockEntryAdviceEnvelope(ENTRY, request.strategy, request.window, request.rivalEntryId);
  return {
    ...base,
    payload: {
      ...base.payload,
      mode: request.strategy,
      window: request.window,
      rival_entry_id: request.rivalEntryId ?? null,
      ...overrides,
    } as EntryAdvice,
  };
}

function renderView(
  search: string,
  client: AdviceClient,
  props: Partial<Parameters<typeof LeagueMemberView>[0]> = {},
) {
  const element = (updated: Partial<Parameters<typeof LeagueMemberView>[0]> = {}) => (
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${search}`]}>
        <LeagueMemberView
          squad={SQUAD}
          advice={null}
          members={MEMBERS}
          index={INDEX}
          client={client}
          capabilities={CAPABILITIES}
          {...props}
          {...updated}
        />
      </MemoryRouter>
    </LanguageProvider>
  );
  const rendered = render(element());
  return {
    ...rendered,
    update: (updated: Partial<Parameters<typeof LeagueMemberView>[0]>) =>
      rendered.rerender(element(updated)),
  };
}

async function pressCompute(): Promise<void> {
  await act(async () => {
    screen.getByRole("button", { name: "Hesapla" }).click();
    await Promise.resolve();
  });
}

describe("a selection nobody published, with the service answering", () => {
  const link = `mode=ortak-koru&window=3&rival=${OTHER_RIVAL}&top100=20`;

  it.each(["hit", "miss", "failure"])("reads the cache on open: %s", async (outcome) => {
    const client = new RecordingClient((request) => ({
      kind: "advice",
      envelope: computed(request),
      source: "api-cache",
    }));
    const read = vi.spyOn(client, "readAdvice");
    if (outcome === "miss") read.mockResolvedValue({ kind: "not-computed" });
    if (outcome === "failure") read.mockRejectedValue(new Error("unreachable"));
    const { container } = renderView(link, client, {
      adviceIssue: "not-listed",
      computeService: "ready",
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(read).toHaveBeenCalledTimes(1);
    expect(client.requests).toEqual([]);
    expect(container).not.toHaveTextContent(copy.computeFailed);
    if (outcome === "hit") {
      await waitFor(() => expect(container).toHaveTextContent(copy.computeDone));
      expect(screen.getByText(PLAN_SHOWN)).toBeVisible();
    } else {
      expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
      expect(container).not.toHaveTextContent(copy.computeDone);
    }
  });

  it.each(["selection", "capture"])(
    "silently ignores an on-open answer for another %s",
    async (mismatch) => {
      const client = new RecordingClient((request) => ({
        kind: "advice",
        source: "api-cache",
        envelope: computed(
          request,
          mismatch === "capture"
            ? { source_snapshot_id: "another-capture" }
            : { mode: "fark-yarat" },
        ),
      }));
      const read = vi.spyOn(client, "readAdvice");
      const { container } = renderView(link, client, {
        adviceIssue: "not-listed",
        computeService: "ready",
      });
      await act(async () => {
        await Promise.resolve();
        await read.mock.results[0]!.value;
      });
      expect(read).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(PLAN_SHOWN)).toBeNull();
      expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
      expect(container).not.toHaveTextContent(copy.computeFailed);
      expect(container).not.toHaveTextContent(computeCopy.failures.ANSWER_OTHER_CAPTURE!);
    },
  );

  it("keeps a finished computed plan when the service becomes unreachable", async () => {
    const client = new RecordingClient((request) => ({
      kind: "advice",
      envelope: computed(request),
      source: "api-cache",
    }));
    const read = vi.spyOn(client, "readAdvice").mockResolvedValue({ kind: "not-computed" });
    const { container, update } = renderView(link, client, {
      adviceIssue: "not-listed",
      computeService: "ready",
    });
    await act(async () => {
      await Promise.resolve();
    });
    await pressCompute();
    await waitFor(() => expect(container).toHaveTextContent(copy.computeDone));
    update({ computeService: "unreachable" });
    expect(screen.getByText(PLAN_SHOWN)).toBeVisible();
    expect(container).toHaveTextContent(copy.computeDone);
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("does not read the cache in a static build", async () => {
    const client = new RecordingClient(() => ({ kind: "unavailable" }));
    const read = vi.spyOn(client, "readAdvice");
    renderView(link, client, { adviceIssue: "not-listed", capabilities: null });
    await act(async () => {
      await Promise.resolve();
    });
    expect(read).not.toHaveBeenCalled();
  });

  it("is offered to Hesapla instead of ending in 'not listed'", () => {
    const { container } = renderView(link, new RecordingClient(() => ({ kind: "unavailable" })), {
      adviceIssue: "not-listed",
    });
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    expect(container).toHaveTextContent(computeCopy.notPrecomputed);
    expect(container).toHaveTextContent(computeCopy.duration[3]);
    expect(container).not.toHaveTextContent(copy.publicationStates["not-listed"].title);
    expect(container).not.toHaveTextContent(copy.computeUnsupportedSelection);
  });

  it("stays the dead end it was on a static build", () => {
    const { container } = renderView(link, new RecordingClient(() => ({ kind: "unavailable" })), {
      adviceIssue: "not-listed",
      capabilities: null,
    });
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();
    expect(container).toHaveTextContent(copy.publicationStates["not-listed"].title);
    expect(container).not.toHaveTextContent(computeCopy.notPrecomputed);
  });

  it("sends the member's switches and shows the computed plan as computed", async () => {
    const client = new RecordingClient((request) => ({
      kind: "advice",
      envelope: computed(request),
      source: "api-cache",
    }));
    const { container } = renderView(link, client, { adviceIssue: "not-listed" });
    await pressCompute();
    expect(client.requests).toHaveLength(1);
    expect(client.requests[0]).toMatchObject({
      entryId: ENTRY,
      strategy: "ortak-koru",
      window: 3,
      rivalEntryId: OTHER_RIVAL,
      top100Weight: 20,
      managersWord: false,
    });
    expect(container).toHaveTextContent(copy.computeDone);
    expect(container.querySelector('[data-testid="top100-influence"]')).not.toBeNull();
  });

  it("refuses a plan the service solved from another capture, in the panel and the card", async () => {
    const client = new RecordingClient((request) => ({
      kind: "advice",
      envelope: computed(request, { source_snapshot_id: "another-capture" }),
      source: "api-cache",
    }));
    const { container } = renderView(link, client, { adviceIssue: "not-listed" });
    await pressCompute();
    expect(container).toHaveTextContent(computeCopy.failures.ANSWER_OTHER_CAPTURE!);
    expect(container).toHaveTextContent(copy.publicationStates["context-mismatch"].title);
    expect(container).not.toHaveTextContent(copy.computeDone);
    expect(container.querySelector('[data-testid="top100-influence"]')).toBeNull();
  });

  it.each([false, true])(
    "resumes a remembered job before reading the cache (missing: %s)",
    async (missing) => {
      const request: AdviceRequest = {
        leagueId: INDEX.league_id,
        entryId: ENTRY,
        strategy: "ortak-koru",
        window: 3,
        rivalEntryId: OTHER_RIVAL,
        top100Weight: 20,
        managersWord: false,
        season: INDEX.season,
        gameweek: INDEX.gameweek,
      };
      rememberJob(request, { jobId: "advice-0123456789abcdef-1", startedAt: Date.now() - 20_000 });
      const client = new RecordingClient((asked) => ({
        kind: "advice",
        envelope: computed(asked),
        source: "api-cache",
      }));
      if (missing)
        vi.spyOn(client, "readJob").mockRejectedValue(new AdviceApiError(404, "JOB_NOT_FOUND"));
      const read = vi.spyOn(client, "readAdvice");
      const { container } = renderView(link, client, {
        adviceIssue: "not-listed",
        computeService: "ready",
      });
      expect(read).not.toHaveBeenCalled();
      expect(container).toHaveTextContent(copy.computeQueued);
      expect(container).toHaveTextContent(computeCopy.leaveOpen);
      await waitFor(() => expect(container).toHaveTextContent(copy.computeDone), { timeout: 4000 });
      if (!missing) expect(client.polls).toEqual(["advice-0123456789abcdef-1"]);
      expect(read).toHaveBeenCalledTimes(1);
      expect(client.requests).toEqual([]);
    },
  );
});

describe("a published selection, with the service answering", () => {
  it("computes an unpublished chip and shows its result without claiming a measured duration", async () => {
    const client = new RecordingClient(() => ({
      kind: "advice",
      source: "api-cache",
      envelope: mockEntryAdviceChipEnvelope(ENTRY, "bboost"),
    }));
    const { container } = renderView("chip=bboost", client, {
      capabilities: { ...CAPABILITIES, chipsByEntry: { [ENTRY]: ["bboost"] } },
    });
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    expect(container).toHaveTextContent(computeCopy.chipDurationUnknown);
    expect(container).not.toHaveTextContent(computeCopy.duration[1]);
    await pressCompute();
    expect(client.requests[0]).toMatchObject({ chip: "bboost" });
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: PLAN_SHOWN })).toBeInTheDocument(),
    );
    expect(screen.getByTestId("chip-choice")).toHaveTextContent(copy.chipNames.bboost);
  });
  it("is shown at once with no request, and Hesapla can still recompute it", async () => {
    const client = new RecordingClient(() => ({ kind: "unavailable" }));
    const read = vi.spyOn(client, "readAdvice");
    const { container } = renderView("", client, {
      advice: mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1),
      computeService: "ready",
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(read).not.toHaveBeenCalled();
    expect(client.requests).toEqual([]);
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    expect(container).toHaveTextContent(computeCopy.duration[1]);
    expect(container).not.toHaveTextContent(computeCopy.notPrecomputed);
  });

  it("keeps a chosen chip published-only", () => {
    const index = {
      ...INDEX,
      chips: {
        available: true as const,
        paths: { wildcard: `advice/${ENTRY}/saf-puan/1/chip-wildcard.json` },
        unavailable: [],
        held: ["wildcard" as const],
      },
    };
    const { container } = renderView(
      "chip=wildcard",
      new RecordingClient(() => ({ kind: "unavailable" })),
      {
        index,
      },
    );
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();
    expect(container).toHaveTextContent(computeCopy.chipUnavailable);
  });
});

describe("a bundle built with an origin whose service is down", () => {
  function open(search = "") {
    const queries = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    return render(
      <QueryClientProvider client={queries}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${search}`]}>
            <Routes>
              <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
  }

  function stubStaticTree() {
    vi.spyOn(data, "loadLeagueMembers").mockResolvedValue(mockLeagueMembersEnvelope);
    vi.spyOn(data, "loadEntrySquad").mockImplementation(async (id) => mockEntrySquadEnvelopes[id]!);
    vi.spyOn(data, "loadEntryAdviceIndex").mockImplementation(async (id) =>
      mockEntryAdviceIndex(id),
    );
    vi.spyOn(data, "loadEntryAdvice").mockImplementation(async (id, mode, window, rival) =>
      mockEntryAdviceEnvelope(id, mode, window, rival),
    );
  }

  it("is the static page with one calm notice, and Hesapla lands on the published plan", async () => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example");
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (input: string) => {
      calls.push(String(input));
      throw new TypeError("Failed to fetch");
    });
    stubStaticTree();
    const { container } = open();
    expect(await screen.findByText(computeCopy.serviceUnreachablePublished)).toBeInTheDocument();
    expect(container).not.toHaveTextContent(computeCopy.serviceUnreachable);
    expect(container).not.toHaveTextContent(computeCopy.serviceUnreachableAbsent);
    const service = "https://squadopt-api.example";
    expect(calls.filter((url) => url.startsWith(service))).toEqual([
      `${service}/api/v1/leagues/${INDEX.league_id}/capabilities`,
    ]);
    // The only other read is the site's own published calendar, which says whether the
    // advised gameweek's deadline has passed. It is a static document, not a service.
    expect(calls.filter((url) => !url.startsWith(service))).toEqual(["/data/fixtures.json"]);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      SQUAD.payload.entry.team_name!,
    );
    expect(container).toHaveTextContent(PLAN_SHOWN);
    expect(screen.queryByRole("alert")).toBeNull();
    // An unpublished selection stays the static dead end: nothing pretends to compute.
    expect(container).not.toHaveTextContent(computeCopy.notPrecomputed);

    await pressCompute();
    await waitFor(() => expect(container).toHaveTextContent(copy.computeStaticFallback));
  });

  it("asks nothing at all when no origin is configured", async () => {
    const fetched = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetched);
    stubStaticTree();
    const { container } = open();
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(container).toHaveTextContent(PLAN_SHOWN));
    // No service is asked anything. The one read is the site's own published calendar.
    expect(fetched.mock.calls.map((call) => String((call as unknown[])[0]))).toEqual([
      "/data/fixtures.json",
    ]);
    expect(container).not.toHaveTextContent(computeCopy.serviceUnreachable);
    expect(container).not.toHaveTextContent(computeCopy.serviceUnreachablePublished);
    expect(container).not.toHaveTextContent(computeCopy.serviceUnreachableAbsent);
  });

  it("offers the unpublished selection once the service answers", async () => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example");
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({
            contract_version: "league_capabilities_v1",
            league_id: INDEX.league_id,
            capture_snapshot_id: SQUAD.payload.source_snapshot_id,
            season: INDEX.season,
            gameweek: INDEX.gameweek,
            strategies: {
              "ortak-koru": { windows: [1, 3, 5], requires_rival: true },
              "saf-puan": { windows: [1, 3, 5], requires_rival: false },
            },
            top100: { available: false, weights: [0] },
            managers_word: { available: false },
          }),
          { status: 200 },
        ),
    );
    stubStaticTree();
    const { container } = open(`mode=ortak-koru&window=5&rival=${OTHER_RIVAL}`);
    expect(await screen.findByText(new RegExp(computeCopy.notPrecomputed))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    expect(container).toHaveTextContent(computeCopy.duration[5]);
  });

  it("says so, and computes nothing, when the service works from another capture", async () => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example");
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({
            contract_version: "league_capabilities_v1",
            league_id: INDEX.league_id,
            capture_snapshot_id: "a-newer-capture",
            season: INDEX.season,
            gameweek: INDEX.gameweek,
            strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
            top100: { available: false, weights: [0] },
            managers_word: { available: false },
          }),
          { status: 200 },
        ),
    );
    stubStaticTree();
    const { container } = open();
    expect(await screen.findByText(computeCopy.otherCapture)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();
    expect(container).toHaveTextContent(PLAN_SHOWN);
  });
});
