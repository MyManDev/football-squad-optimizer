import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { readReply } from "../../../testSupport/intentReply";
import { requestsCarrying, sentRequests, watchKeyLeaks } from "../../../testSupport/keyLeaks";
import { stubTree, withLeague } from "../../../testSupport/league";
import type { AdviceRequest } from "../advice/adviceClient";
import type { ComputePhase } from "../advice/useAdviceJob";
import { leagueKeys } from "../queries";
import { FIXTURES_QUERY } from "../../fixtures/data";
import { LLMOPT_COPY } from "./copy";
import { IntentError, MAX_MESSAGE_LENGTH, intentBody } from "./intent";
import type { IntentSource } from "./intentSource";
import { clearOwnKey, heldModel } from "./ownKey";
import { summarizeRevision } from "./planRevision";
import type { LLMOptPage as Page } from "./LLMOptPage";

interface FakeJob {
  compute: Mock<(request: AdviceRequest) => void>;
  resume: Mock<(request: AdviceRequest) => boolean>;
  readCached: Mock<(request: AdviceRequest) => void>;
  reset: Mock<() => void>;
  show: (state: ComputePhase) => void;
}

// The page's advice jobs (base, first, second, combined), in the order each render mounted them.
const jobs = vi.hoisted(() => [] as FakeJob[]);

vi.mock("../advice/useAdviceJob", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../advice/useAdviceJob")>();
  return {
    ...actual,
    useAdviceJob: () => {
      const [state, setState] = useState<ComputePhase>({ phase: "idle" });
      const [job] = useState<FakeJob>(() => {
        const made: FakeJob = {
          compute: vi.fn((request: AdviceRequest) => setState({ phase: "requesting", request })),
          resume: vi.fn(() => false),
          readCached: vi.fn(),
          reset: vi.fn(() => setState({ phase: "idle" })),
          show: setState,
        };
        jobs.push(made);
        return made;
      });
      return { state, ...job };
    },
  };
});

const ORIGIN = "https://advice.example";
const ENTRY = 35249001;
const envelope = mockEntrySquadEnvelopes[ENTRY]!;
const squad = envelope.payload;
const OWNED = [...squad.starting_xi, ...squad.bench];
const OUTSIDER = { id: 990001, name: "Outside Signing", team: "Arsenal" };
const ROSTER = [
  ...OWNED.map(({ player_id, name, team }) => ({ id: player_id, name, team })),
  OUTSIDER,
];
const en = LLMOPT_COPY.en;
// One deadline for every visit in a test, so a reload finds the session it saved.
const DEADLINE = new Date(Date.now() + 86_400_000).toISOString();
const CALENDAR = {
  season: squad.season,
  source_snapshot_id: "fixtures",
  captured_at_utc: "2026-01-01T00:00:00Z",
  current_gameweek: squad.gameweek,
  unscheduled_count: 0,
  gameweeks: [{ gameweek: squad.gameweek, deadline_utc: DEADLINE, fixtures: [] }],
};

let LLMOptPage: typeof Page;
let roster: "ok" | "fail" | "late";
let releaseRoster: () => void;
let releaseEnabled: boolean;
let threeWeekEnabled: boolean;
let bundlesOffered: boolean;
let repairsOffered: boolean;
let rosterGate: Promise<void>;
let intent: Mock<(body: Record<string, unknown>) => Response>;
const clients: QueryClient[] = [];

beforeAll(async () => {
  vi.stubEnv("VITE_ADVICE_API_ORIGIN", ORIGIN);
  ({ LLMOptPage } = await import("./LLMOptPage"));
});

beforeEach(() => {
  jobs.length = 0;
  releaseEnabled = true;
  threeWeekEnabled = false;
  bundlesOffered = false;
  repairsOffered = false;
  roster = "ok";
  rosterGate = new Promise<void>((resolve) => (releaseRoster = resolve));
  intent = vi.fn(
    () =>
      new Response(
        JSON.stringify({ status: "clarification", message: "Which week should it be?" }),
      ),
  );
  stubTree({ entrySquad: vi.fn(async () => envelope) });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === `${ORIGIN}/api/v1/leagues/${squad.league_id}/capabilities`) {
        return Response.json({
          contract_version: "league_capabilities_v1",
          league_id: squad.league_id,
          capture_snapshot_id: squad.source_snapshot_id,
          season: squad.season,
          gameweek: squad.gameweek,
          strategies: { "saf-puan": { windows: [1, 3], requires_rival: false } },
          preferences: { available: true },
          top100: { available: false, weights: [0] },
          managers_word: { available: false },
          ...(releaseEnabled ? { llmopt_vnext: true } : {}),
          ...(threeWeekEnabled ? { llmopt_vnext_three_week: true } : {}),
          ...(repairsOffered ? { verified_repairs: true } : {}),
          ...(bundlesOffered
            ? { preference_bundles: { version: "llmopt_preference_bundle_v1" } }
            : {}),
        });
      }
      if (url === `${ORIGIN}/api/v1/contributions/players`) {
        if (roster === "fail") return new Response("{}", { status: 503 });
        if (roster === "late") await rosterGate;
        return new Response(JSON.stringify({ season: squad.season, players: ROSTER }));
      }
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  cleanup();
  clearOwnKey();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  history.replaceState(null, "");
});

/** Stands in for a held model: `intent` answers the body the page would send to be checked. */
const model: IntentSource = {
  interpret: async (request) =>
    readReply(
      intent(
        intentBody(
          request.message,
          request.locale,
          request.draft,
          request.players,
          request.clarification,
          request.referenceWeeks,
          request.referenceCaptains,
        ),
      ),
      request.players,
    ),
};

/**
 * Opens the page the way a visit or a reload does: a fresh query cache, the tab's storage kept.
 * The chat is read by `intentSource`; null leaves it to the member's own key, as on the site.
 */
function open(
  language: "en" | "tr" = "en",
  intentSource: IntentSource | null = model,
  calendar: typeof CALENDAR | null = CALENDAR,
  previousRelease?: boolean,
) {
  // The fixtures are set, not read, so the cache keeps them while no page observes them.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  client.setQueryData(FIXTURES_QUERY.queryKey, calendar);
  if (previousRelease !== undefined) {
    client.setQueryData(leagueKeys.restoredPlanCapabilities(ORIGIN, false, squad), {
      llmoptVNext: previousRelease,
      leagueId: squad.league_id,
      season: squad.season,
      gameweek: squad.gameweek,
      captureSnapshotId: squad.source_snapshot_id,
    });
  }
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/entry/${ENTRY}/llmopt`]}>
          {withLeague(
            <Routes>
              <Route
                path="/entry/:entryId/llmopt"
                element={<LLMOptPage intentSource={intentSource ?? undefined} />}
              />
            </Routes>,
          )}
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

function failCapabilitiesRead() {
  const originalFetch = globalThis.fetch;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === `${ORIGIN}/api/v1/leagues/${squad.league_id}/capabilities`
      ? Promise.resolve(new Response(null, { status: 503 }))
      : originalFetch(input, init),
  );
}

async function ready() {
  return screen.findByRole("heading", { level: 1, name: en.title });
}

async function sendMessage(text: string, language: "en" | "tr" = "en") {
  const user = userEvent.setup();
  const copy = LLMOPT_COPY[language];
  await user.type(screen.getByRole("textbox", { name: copy.chat }), text);
  const send = screen.getByRole("button", { name: copy.send });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
}

it.each([
  ["PATIENCE_EXHAUSTED", "wait"],
  ["RUN_BUDGET_EXHAUSTED", "budget"],
  ["MODEL_INPUTS_UNAVAILABLE", "missing"],
] as const)(
  "closes the previous main after an explicit retry of %s without editing the draft",
  async (reason, notice) => {
    repairsOffered = true;
    const normalFetch = globalThis.fetch;
    const cancelled: string[] = [];
    let allowCancel = false;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
      const id = String(input).match(/\/runs\/([a-f0-9]{32})\/cancel$/)?.[1];
      if (!id) return normalFetch(input, init);
      expect(init?.method).toBe("POST");
      cancelled.push(id);
      return Promise.resolve(new Response("{}", { status: allowCancel ? 200 : 503 }));
    });
    open();
    await ready();
    await addRule("no_hits");
    await userEvent.click(screen.getByRole("button", { name: en.compute }));
    const base = jobs[0]!;
    await waitFor(() => expect(base.compute).toHaveBeenCalledTimes(1));
    const first = base.compute.mock.calls[0]![0];
    act(() => base.show({ phase: "failed", request: first, reason }));
    expect(await screen.findByText(en.repairs[notice])).toBeVisible();
    const retry = screen.getByRole("button", { name: en.compute });
    expect(retry).toBeEnabled();
    expect(cancelled).toEqual([]);
    await userEvent.click(retry);
    await screen.findByText(en.serviceUnavailable);
    expect(base.compute).toHaveBeenCalledTimes(1);
    allowCancel = true;
    await userEvent.click(retry);
    await waitFor(() => expect(base.compute).toHaveBeenCalledTimes(2));
    expect(cancelled).toEqual([first.run!.run_id, first.run!.run_id]);
    const fresh = base.compute.mock.calls[1]![0];
    expect(fresh.run?.run_id).toMatch(/^[0-9a-f]{32}$/);
    expect(fresh.run?.run_id).not.toBe(first.run!.run_id);
    expect(fresh.preferences).toEqual(first.preferences);
    expect(fresh.run?.stage).toBe("base");
    expect(jobs.slice(1).every((job) => !job.compute.mock.calls.length)).toBe(true);
  },
);

describe("chat keyboard focus", () => {
  it.each(["clarification", "refusal"])("returns to the chat after a %s", async (outcome) => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => (release = resolve));
    open("en", {
      interpret: async () => {
        await pending;
        if (outcome === "refusal") throw new Error("Provider unavailable");
        return { status: "clarification", message: "Which week?" };
      },
    });
    await ready();
    const input = screen.getByRole("textbox", { name: en.chat });
    await sendMessage("Buy a striker.");
    expect(input).toBeDisabled();
    await act(async () => release());
    await waitFor(() => expect(input).toBeEnabled());
    expect(input).toHaveFocus();
  });

  it("keeps focus where the member moved while an answer was pending", async () => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => (release = resolve));
    open("en", {
      interpret: async () => {
        await pending;
        return { status: "clarification", message: "Which week?" };
      },
    });
    await ready();
    await sendMessage("Buy a striker.");
    const rule = screen.getByRole("combobox", { name: en.rule });
    await userEvent.click(rule);
    expect(rule).toHaveFocus();
    await act(async () => release());
    await waitFor(() => expect(screen.getByRole("textbox", { name: en.chat })).toBeEnabled());
    expect(rule).toHaveFocus();
  });
});

describe("chat refusals", () => {
  it.each([
    [503, "PROVIDER_UNAVAILABLE", en.refusals.busy],
    [422, "REPLY_REFUSED", en.refusals.replyInvalid],
    [502, "PROVIDER_REPLY_CUT", en.refusals.replyCut],
    [402, "PROVIDER_ACCOUNT_REFUSED", en.refusals.accountRefused],
    [429, "RATE_LIMITED", en.refusals.limited],
    [413, "PAYLOAD_TOO_LARGE", en.refusals.tooLarge],
    [422, "VALIDATION_FAILED", en.refusals.invalid],
    [415, "UNSUPPORTED_MEDIA_TYPE", en.refusals.unsupported],
  ] as const)("shows a %i %s refusal in its own words", async (status, code, words) => {
    intent.mockImplementation(
      () => new Response(JSON.stringify({ error: { code, message: "operator" } }), { status }),
    );
    open();
    await ready();
    await sendMessage("Roll the transfer.");

    expect(await screen.findByText(words, { exact: true })).toBeVisible();
    for (const other of Object.values(en.refusals).filter((text) => text !== words))
      expect(screen.queryByText(other, { exact: true })).toBeNull();
  });

  it("keeps every answer when the model asks a second question", async () => {
    open();
    await ready();
    await sendMessage("Buy a striker.");
    await screen.findByText("Which week should it be?");
    await sendMessage("Next week.");
    await waitFor(() => expect(intent).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("textbox", { name: en.chat })).toHaveValue(""));
    await sendMessage("Haaland.");
    await waitFor(() => expect(intent).toHaveBeenCalledTimes(3));
    // The third request still carries the answer to the first question.
    expect(intent.mock.calls[2]?.[0]).toMatchObject({
      message: "Haaland.",
      clarification: {
        message: "Buy a striker.\nNext week.",
        question: "Which week should it be?",
      },
    });
  });

  it("preserves the answer and asks for a shorter request when another question cannot keep the context", async () => {
    open();
    await ready();
    const input = screen.getByRole("textbox", { name: en.chat });
    const first = "Buy a striker.".padEnd(MAX_MESSAGE_LENGTH, ".");
    fireEvent.change(input, { target: { value: first } });
    await userEvent.click(screen.getByRole("button", { name: en.send }));
    await screen.findByText("Which week should it be?");
    await sendMessage("Next week.");
    await waitFor(() => expect(intent).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(input).toHaveValue("Next week."));
    expect(screen.getByText(en.conversationTooLong)).toBeVisible();
    expect(screen.getByRole("button", { name: en.dismissQuestion })).toBeVisible();
    expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: en.dismissQuestion }));
    intent.mockReturnValue(
      new Response(
        JSON.stringify({ status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } }),
      ),
    );
    fireEvent.change(input, { target: { value: "Buy a striker next week. No hits." } });
    await userEvent.click(screen.getByRole("button", { name: en.send }));
    await waitFor(() => expect(intent).toHaveBeenCalledTimes(3));
    expect(intent.mock.calls[2]?.[0].clarification).toBeUndefined();
    await waitFor(() => expect(screen.getByRole("button", { name: en.compute })).toBeEnabled());
  });

  it("keeps the workspace when a later refresh of the squad fails", async () => {
    const entrySquad = vi.fn(async () => envelope);
    stubTree({ entrySquad });
    open();
    await ready();
    await userEvent.click(screen.getByRole("button", { name: en.add }));
    entrySquad.mockRejectedValue(new Error("offline"));
    await clients[0]!.refetchQueries();
    expect(entrySquad.mock.calls.length).toBeGreaterThan(1);
    expect(screen.getByRole("heading", { level: 1, name: en.title })).toBeVisible();
    expect(screen.queryByText(en.squadUnavailable)).toBeNull();
    expect(
      screen.getByRole("button", { name: `${en.remove} · ${en.rules.hold_transfers}` }),
    ).toBeVisible();
  });

  it.each(["offline", "unavailable", "unreadable"] as const)(
    "keeps the draft and running jobs when the fixture refresh is %s",
    async (failure) => {
      open();
      await ready();
      await addRule("include_player", OUTSIDER.name);
      await act(async () => {
        jobs[0]!.show({
          phase: "waiting",
          request: { leagueId: squad.league_id, entryId: ENTRY, strategy: "saf-puan", window: 1 },
          jobId: "fixtures-running-job",
          status: null,
          fallback: null,
        });
      });
      const input = screen.getByRole("textbox", { name: en.chat });
      const existingJobs = [...jobs];
      const originalFetch = fetch;
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
          if (!String(input).endsWith("data/fixtures.json")) return originalFetch(input, init);
          if (failure === "offline") throw new TypeError("offline");
          if (failure === "unavailable") return new Response("unavailable", { status: 503 });
          return new Response("<html>temporary error</html>", { status: 200 });
        }),
      );
      await act(async () => {
        await clients[0]!.refetchQueries({ queryKey: FIXTURES_QUERY.queryKey, exact: true });
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      expect(clients[0]!.getQueryData(FIXTURES_QUERY.queryKey)).toBeNull();
      expect(screen.getByRole("textbox", { name: en.chat })).toBe(input);
      expect(
        screen.getByRole("button", {
          name: `${en.remove} · ${en.rules.include_player} · ${OUTSIDER.name}`,
        }),
      ).toBeVisible();
      expect(jobs).toEqual(existingJobs);
    },
  );

  it("keeps Send off while Retry-After runs and turns it back on by itself", async () => {
    intent.mockImplementationOnce(
      () =>
        new Response(JSON.stringify({ error: { code: "RATE_LIMITED", message: "operator" } }), {
          status: 429,
          headers: { "Retry-After": "2" },
        }),
    );
    open();
    await ready();
    await sendMessage("Roll the transfer.");

    const send = screen.getByRole("button", { name: en.send });
    expect(await screen.findByText(en.limitedFor(2), { exact: true })).toBeVisible();
    expect(send).toBeDisabled();
    await userEvent.click(send);
    expect(intent).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(send).toBeEnabled(), { timeout: 4000 });
    expect(screen.queryByText(/You can send again/)).toBeNull();
    await userEvent.click(send);
    await screen.findByText("Which week should it be?");
    expect(intent).toHaveBeenCalledTimes(2);
    // The service keeps no roster between requests, so each request carries it.
    expect(intent.mock.calls[1]?.[0]).toMatchObject({
      players: expect.arrayContaining([expect.objectContaining({ id: OUTSIDER.id })]),
    });
  });

  it("words the wait in Turkish", () => {
    expect(LLMOPT_COPY.tr.limitedFor(45)).toBe(
      "Sohbet istek sınırına ulaştı. 45 saniye sonra tekrar gönderebilirsin.",
    );
    expect(LLMOPT_COPY.tr.limitedFor(86_400)).toContain("24 saat");
    expect(en.limitedFor(1)).toContain("in 1 second.");
    expect(en.limitedFor(60)).toContain("in 1 minute.");
    expect(en.limitedFor(90)).toContain("in 2 minutes.");
  });
});

/** The tab's saved LLMOPT session for the example member. */
function savedSession(): [string, Record<string, unknown>] {
  const keys = Array.from({ length: sessionStorage.length }, (_, index) =>
    sessionStorage.key(index),
  );
  const key = keys.find((name) => name?.startsWith("squadopt.llmopt:")) ?? undefined;
  expect(key).toBeDefined();
  return [key!, JSON.parse(sessionStorage.getItem(key!)!) as Record<string, unknown>];
}

async function addRule(kind: string, player?: string) {
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText(en.rule), kind);
  if (player) {
    const option = await screen.findByRole("option", { name: new RegExp(`^${player} · `) });
    await user.selectOptions(screen.getByLabelText(en.player), option);
  }
  await user.click(screen.getByRole("button", { name: en.add }));
}

describe("a reload keeps the saved session", () => {
  const outsiderRule = `${en.rules.include_player} · ${OUTSIDER.name}`;

  it.each(["disabled", "full"] as const)(
    "keeps the latest rules after a basis refresh when storage is %s",
    async (failure) => {
      const entrySquad = vi.fn(async () => envelope);
      stubTree({ entrySquad });
      open();
      await ready();
      if (failure === "full") await addRule("hold_transfers");
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new DOMException(
          "Storage unavailable",
          failure === "full" ? "QuotaExceededError" : "SecurityError",
        );
      });
      if (failure === "disabled")
        vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
          throw new DOMException("Storage unavailable", "SecurityError");
        });
      await addRule("no_hits");
      const noHits = `${en.remove} · ${en.rules.no_hits}`;
      expect(screen.getByRole("button", { name: noHits })).toBeVisible();
      entrySquad.mockResolvedValue({
        ...envelope,
        payload: { ...squad, bank_tenths: squad.bank_tenths + 1 },
      });
      await act(async () => {
        await clients.at(-1)!.refetchQueries({
          queryKey: leagueKeys.entrySquad(squad.league_id, ENTRY),
          exact: true,
        });
      });
      await waitFor(() => expect(jobs).toHaveLength(8));
      expect(screen.getByRole("button", { name: noHits })).toBeVisible();
      expect(screen.queryByRole("region", { name: en.results })).toBeNull();
      for (const job of jobs.slice(4)) {
        expect(job.compute).not.toHaveBeenCalled();
        expect(job.resume).not.toHaveBeenCalled();
        expect(job.readCached).not.toHaveBeenCalled();
      }
    },
  );

  it("keeps rules edited before the initially missing deadline is published", async () => {
    open("en", model, null);
    await ready();
    await addRule("include_player", OUTSIDER.name);
    expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();
    await act(async () => {
      clients.at(-1)!.setQueryData(FIXTURES_QUERY.queryKey, CALENDAR);
    });
    await waitFor(() => {
      expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible();
      expect(screen.getByRole("button", { name: en.compute })).toBeEnabled();
    });
    await waitFor(() =>
      expect(savedSession()[1]).toMatchObject({
        draft: { hard: [{ kind: "include_player", player_id: OUTSIDER.id }] },
      }),
    );
    cleanup();
    open();
    expect(await screen.findByText(outsiderRule, { exact: true })).toBeVisible();
  });

  it.each(["bank", "snapshot"] as const)(
    "keeps the draft when a successful %s refresh follows an unavailable calendar",
    async (changed) => {
      const entrySquad = vi.fn(async () => envelope);
      stubTree({ entrySquad });
      open();
      await ready();
      await addRule("include_player", OUTSIDER.name);
      await act(async () => {
        clients.at(-1)!.setQueryData(FIXTURES_QUERY.queryKey, null);
      });
      expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible();
      expect(jobs).toHaveLength(4);

      entrySquad.mockResolvedValue({
        ...envelope,
        payload: {
          ...squad,
          ...(changed === "bank"
            ? { bank_tenths: squad.bank_tenths + 1 }
            : { source_snapshot_id: "fresh-capture-with-calendar-offline" }),
        },
      });
      await act(async () => {
        await clients.at(-1)!.refetchQueries({
          queryKey: leagueKeys.entrySquad(squad.league_id, ENTRY),
          exact: true,
        });
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await waitFor(() => expect(jobs).toHaveLength(8));
      expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible();
      expect(screen.queryByRole("region", { name: en.results })).toBeNull();
    },
  );

  it.each(["gameweek", "season"] as const)(
    "does not reuse an unavailable calendar's old deadline for another %s",
    async (changed) => {
      const entrySquad = vi.fn(async () => envelope);
      stubTree({ entrySquad });
      open();
      await ready();
      await addRule("include_player", OUTSIDER.name);
      await act(async () => {
        clients.at(-1)!.setQueryData(FIXTURES_QUERY.queryKey, null);
      });
      entrySquad.mockResolvedValue({
        ...envelope,
        payload: {
          ...squad,
          ...(changed === "gameweek" ? { gameweek: squad.gameweek + 1 } : { season: "2027-28" }),
        },
      });
      await act(async () => {
        await clients.at(-1)!.refetchQueries({
          queryKey: leagueKeys.entrySquad(squad.league_id, ENTRY),
          exact: true,
        });
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await waitFor(() => expect(jobs).toHaveLength(8));
      expect(screen.queryByText(outsiderRule, { exact: true })).toBeNull();
      expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();
    },
  );

  it.each(["bank", "snapshot"] as const)(
    "keeps the latest rules and drops the old run after a successful %s refresh",
    async (changed) => {
      const entrySquad = vi.fn(async () => envelope);
      stubTree({ entrySquad });
      open();
      await ready();
      await addRule("include_player", OUTSIDER.name);
      cleanup();
      const [key, saved] = savedSession();
      sessionStorage.setItem(
        key,
        JSON.stringify({
          ...saved,
          reference: summarizeRevision(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload),
          confirmation: { runId: "a".repeat(32), wildcardNotHeld: false, sending: true },
        }),
      );
      jobs.length = 0;
      open();
      await ready();
      await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));

      entrySquad.mockResolvedValue({
        ...envelope,
        payload: {
          ...squad,
          ...(changed === "bank"
            ? { bank_tenths: squad.bank_tenths + 1 }
            : { source_snapshot_id: "fresh-squad-capture" }),
        },
      });
      await clients.at(-1)!.refetchQueries({
        queryKey: leagueKeys.entrySquad(squad.league_id, ENTRY),
        exact: true,
      });
      await waitFor(() => expect(jobs).toHaveLength(8));
      await waitFor(() => expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible());
      expect(screen.queryByRole("region", { name: en.results })).toBeNull();
      for (const job of jobs.slice(4)) {
        expect(job.compute).not.toHaveBeenCalled();
        expect(job.resume).not.toHaveBeenCalled();
        expect(job.readCached).not.toHaveBeenCalled();
      }

      await addRule("no_hits");
      expect(savedSession()[1]).toMatchObject({
        draft: { hard: [{ kind: "include_player", player_id: OUTSIDER.id }, { kind: "no_hits" }] },
      });
      expect(savedSession()[1]).not.toHaveProperty("confirmation");
      expect(savedSession()[1]).not.toHaveProperty("reference");
      cleanup();
      open();
      await ready();
      expect(await screen.findByText(outsiderRule, { exact: true })).toBeVisible();
      expect(
        screen.getByRole("button", {
          name: `${en.remove} · ${en.rules.no_hits}`,
        }),
      ).toBeVisible();
    },
  );

  it("holds the session while the roster read fails and restores it on Retry", async () => {
    open();
    await ready();
    await addRule("include_player", OUTSIDER.name);
    expect(screen.getByText(outsiderRule, { exact: true })).toBeVisible();
    cleanup();

    roster = "fail";
    open();
    await ready();
    const retry = await screen.findByRole("button", { name: en.retry });
    expect(screen.getByText(en.rosterUnavailable, { exact: false })).toBeVisible();
    expect(screen.queryByText(outsiderRule, { exact: true })).toBeNull();
    expect(savedSession()[1]).toMatchObject({
      draft: { hard: [{ kind: "include_player", player_id: OUTSIDER.id }] },
    });

    roster = "ok";
    await userEvent.click(retry);
    expect(await screen.findByText(outsiderRule, { exact: true })).toBeVisible();
    expect(screen.queryByText(en.rosterUnavailable, { exact: false })).toBeNull();
  });

  it("restores a session that names only squad players even while the roster fails", async () => {
    open();
    await ready();
    await addRule("hold_transfers");
    cleanup();

    roster = "fail";
    open();
    await ready();
    expect(
      await screen.findByRole("button", { name: `${en.remove} · ${en.rules.hold_transfers}` }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: en.retry })).toBeVisible();
  });

  it("waits for a late roster before restoring", async () => {
    open();
    await ready();
    await addRule("include_player", OUTSIDER.name);
    cleanup();

    roster = "late";
    open();
    expect(await screen.findByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    releaseRoster();
    expect(await screen.findByText(outsiderRule, { exact: true })).toBeVisible();
  });

  async function reloadConfirmed(
    confirmation: Record<string, unknown>,
    previousRelease?: boolean,
    window: 1 | 3 = 1,
  ) {
    open();
    await ready();
    await addRule("hold_transfers");
    cleanup();
    const [key, session] = savedSession();
    sessionStorage.setItem(
      key,
      JSON.stringify({
        ...session,
        draft: { ...(session.draft as Record<string, unknown>), window },
        confirmation: { runId: "a".repeat(32), ...confirmation },
      }),
    );
    jobs.length = 0;
    open("en", model, CALENDAR, previousRelease);
    await ready();
    return jobs[0]!;
  }

  it.each([false, true])(
    "restores an answered session without an identity with the flag %s",
    async (enabled) => {
      releaseEnabled = enabled;
      const base = await reloadConfirmed({ runId: undefined, wildcardNotHeld: false });
      await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
      expect(base.compute).not.toHaveBeenCalled();
      expect(base.readCached.mock.calls[0]![0]).not.toHaveProperty("run");
    },
  );

  it("reads the saved job and cache after rollback without posting the interrupted run", async () => {
    releaseEnabled = false;
    const base = await reloadConfirmed({ wildcardNotHeld: false, sending: true }, true);
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    expect(base.resume).toHaveBeenCalledTimes(1);
    expect(base.readCached.mock.calls[0]![0].run?.run_id).toBe("a".repeat(32));
    for (const job of jobs) expect(job.compute).not.toHaveBeenCalled();
  });

  it.each([
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ])(
    "reads an answered, identity-free three-week session with master=%s and three weeks=%s",
    async (master, threeWeek) => {
      releaseEnabled = master!;
      threeWeekEnabled = threeWeek!;
      const base = await reloadConfirmed(
        { runId: undefined, wildcardNotHeld: false },
        undefined,
        3,
      );
      await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
      const request = base.readCached.mock.calls[0]![0];
      expect(request.window).toBe(3);
      expect(request).not.toHaveProperty("run");
      expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
    },
  );

  it.each([
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ])(
    "resumes an interrupted three-week submission only with both grants (master=%s, three weeks=%s)",
    async (master, threeWeek) => {
      releaseEnabled = master!;
      threeWeekEnabled = threeWeek!;
      const base = await reloadConfirmed({ wildcardNotHeld: false, sending: true }, true, 3);
      const allowed = master && threeWeek;
      const method = allowed ? base.compute : base.readCached;
      await waitFor(() => expect(method).toHaveBeenCalledTimes(1));
      expect(method.mock.calls[0]![0]).toMatchObject({
        window: 3,
        run: { run_id: "a".repeat(32) },
      });
      expect(base.resume).toHaveBeenCalledTimes(1);
      if (!allowed) expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
    },
  );

  it.each([false, true])(
    "uses the current release setting %s for the first explicit comparison",
    async (enabled) => {
      releaseEnabled = enabled;
      intent.mockImplementation(() =>
        Response.json({
          status: "draft",
          draft: {
            hard: [{ kind: "no_hits" }],
            soft: [],
            comparison: { kind: "include_player", player_id: OUTSIDER.id },
          },
        }),
      );
      open();
      await ready();
      await sendMessage("Compare including Outside Signing");
      await screen.findByText(en.understood);
      await userEvent.click(screen.getByRole("button", { name: en.compute }));
      await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
      const [base, first] = jobs;
      if (enabled) {
        expect(base!.compute.mock.calls[0]![0].run?.stage).toBe("base");
        expect(first!.compute).not.toHaveBeenCalled();
      } else {
        expect(base!.compute.mock.calls[0]![0]).not.toHaveProperty("run");
        expect(first!.compute).toHaveBeenCalledTimes(1);
        expect(first!.compute.mock.calls[0]![0]).not.toHaveProperty("run");
      }
    },
  );

  it("says how long a 3-week plan takes while it is computed", async () => {
    threeWeekEnabled = true;
    open();
    await ready();
    await addRule("hold_transfers");
    cleanup();
    const [key, session] = savedSession();
    sessionStorage.setItem(
      key,
      JSON.stringify({
        ...session,
        draft: { ...(session.draft as Record<string, unknown>), window: 3 },
        confirmation: { runId: "a".repeat(32), wildcardNotHeld: false, sending: true },
      }),
    );
    jobs.length = 0;
    open();
    await ready();
    await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
    expect(screen.getByText(en.longWait)).toBeVisible();
  });

  it("asks again for a slot whose job a reload right after Compute could not resume", async () => {
    // What Compute saves before its requests are answered: the confirmed run, still sending.
    const base = await reloadConfirmed({ wildcardNotHeld: false, sending: true });
    await waitFor(() => expect(base.compute).toHaveBeenCalledTimes(1));
    expect(base.resume).toHaveBeenCalledTimes(1);
    expect(base.readCached).not.toHaveBeenCalled();
    expect(base.compute.mock.calls[0]?.[0]).toMatchObject({
      entryId: ENTRY,
      preferences: { hold_transfers: true },
    });
    const results = screen.getByRole("region", { name: en.results });
    expect(results).toHaveTextContent(en.computing);
    expect(results).not.toHaveTextContent(en.resultUnavailable);
    // A one-week plan is quick: it says nothing about the wait.
    expect(screen.queryByText(en.longWait)).toBeNull();

    // Once the request has its job, the saved run no longer asks again on the next reload.
    base.show({
      phase: "waiting",
      request: base.compute.mock.calls[0]![0],
      jobId: "job",
      status: null,
      fallback: null,
    });
    await waitFor(() => expect(savedSession()[1]).not.toHaveProperty("confirmation.sending"));
  });

  it("retries an interrupted legacy request without a run identity after the capabilities read fails", async () => {
    failCapabilitiesRead();
    const base = await reloadConfirmed(
      { runId: undefined, wildcardNotHeld: false, sending: true },
      true,
    );
    await waitFor(() => expect(base.compute).toHaveBeenCalledTimes(1));
    expect(base.resume).toHaveBeenCalledTimes(1);
    expect(base.compute.mock.calls[0]![0]).not.toHaveProperty("run");
    expect(base.readCached).not.toHaveBeenCalled();
  });

  it("reads, without sending again, a run whose requests were all answered", async () => {
    const base = await reloadConfirmed({ wildcardNotHeld: false });
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    expect(base.compute).not.toHaveBeenCalled();
  });
});

describe("the plan the member compares against", () => {
  it("stays the chosen plan when a rule is edited after a result", async () => {
    const chosen = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
    const reference = JSON.parse(
      JSON.stringify(
        summarizeRevision({ ...chosen, expected_own_points: 40, bank_after_tenths: 3 }),
      ),
    ) as unknown;
    open();
    await ready();
    await addRule("hold_transfers");
    cleanup();
    const [key, session] = savedSession();
    sessionStorage.setItem(
      key,
      JSON.stringify({ ...session, reference, confirmation: { wildcardNotHeld: false } }),
    );

    jobs.length = 0;
    open();
    await ready();
    const base = jobs[0]!;
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    const shown = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    base.show({
      phase: "done",
      source: "api-cache",
      request: base.readCached.mock.calls[0]![0],
      envelope: { ...shown, payload: { ...shown.payload, bank_after_tenths: 9 } },
    });
    expect(await screen.findByRole("heading", { name: en.base })).toBeVisible();
    expect(savedSession()[1].reference).toEqual(reference);

    await addRule("no_hits");
    expect(savedSession()[1]).toMatchObject({
      draft: { hard: [{ kind: "hold_transfers" }, { kind: "no_hits" }] },
      reference,
    });
  });
});

describe("a model answer that changes the draft", () => {
  it("marks the rules it added, changed and removed until the next edit", async () => {
    intent.mockImplementation(
      () =>
        new Response(
          JSON.stringify({
            status: "draft",
            draft: {
              hard: [{ kind: "save_chips" }, { kind: "no_hits" }],
              soft: [],
              comparison: { kind: "include_player", player_id: OUTSIDER.id },
            },
          }),
        ),
    );
    open();
    await ready();
    await addRule("hold_transfers");
    await addRule("save_chips");
    await sendMessage("No hits, keep the chips, and compare Outside Signing.");
    await screen.findByText(en.understood);

    const item = (name: string) =>
      screen.getByRole("button", { name: `${en.remove} · ${name}` }).closest("li")!;
    expect(item(en.rules.no_hits)).toHaveAttribute("data-change", "added");
    expect(item(en.rules.no_hits)).toHaveTextContent(en.changes.added);
    expect(item(`${en.rules.include_player} · ${OUTSIDER.name}`)).toHaveAttribute(
      "data-change",
      "added",
    );
    expect(item(en.rules.save_chips)).not.toHaveAttribute("data-change");
    const removed = screen.getByText(en.rules.hold_transfers, { selector: "del" });
    expect(removed.closest("li")).toHaveAttribute("data-change", "removed");
    expect(removed.closest("li")).toHaveTextContent(en.changes.removed);

    await userEvent.click(
      screen.getByRole("button", { name: `${en.remove} · ${en.rules.save_chips}` }),
    );
    expect(screen.queryByText(en.changes.added)).toBeNull();
    expect(screen.queryByText(en.rules.hold_transfers, { selector: "del" })).toBeNull();
  });
});

describe("the chat's intent source", () => {
  it("reads the chat through the source the page is given, with the draft and roster", async () => {
    const interpret = vi.fn<IntentSource["interpret"]>(async () => ({
      status: "draft",
      draft: { hard: [{ kind: "no_hits" }], soft: [] },
    }));
    open("en", { interpret });
    await ready();
    await sendMessage("No hits.");

    expect(
      await screen.findByRole("button", { name: `${en.remove} · ${en.rules.no_hits}` }),
    ).toBeVisible();
    expect(intent).not.toHaveBeenCalled();
    expect(interpret).toHaveBeenCalledTimes(1);
    expect(interpret.mock.calls[0]?.[0]).toMatchObject({
      message: "No hits.",
      locale: "en",
      draft: { hard: [], soft: [] },
      players: expect.arrayContaining([expect.objectContaining({ id: OUTSIDER.id })]),
    });
    expect(interpret.mock.calls[0]?.[1]).toBeInstanceOf(AbortSignal);
  });

  it("shows a refusal the source names in the page's own words", async () => {
    open("en", {
      interpret: async () => {
        throw new IntentError(401, "PROVIDER_KEY_REFUSED");
      },
    });
    await ready();
    await sendMessage("No hits.");
    expect(await screen.findByText(en.refusals.keyRefused, { exact: true })).toBeVisible();
  });
});

describe("the plan with all preferences", () => {
  // Three preferred rules: two get a slot each, the third has none of its own.
  const soft = [
    { kind: "no_hits" },
    { kind: "include_player", player_id: OUTSIDER.id },
    { kind: "hit_budget", points: 4 },
  ];
  const labels = [
    en.rules.no_hits,
    `${en.rules.include_player} · ${OUTSIDER.name}`,
    `${en.rules.hit_budget} · ${en.hitBudgetPoints(4)}`,
  ];
  const signing = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload.moves;

  function answer(job: FakeJob, request: AdviceRequest, net: number, moves = signing) {
    const shown = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    job.show({
      phase: "done",
      source: "api-cache",
      request,
      envelope: {
        ...shown,
        payload: {
          ...shown.payload,
          plan_weeks: undefined,
          lineup_expectation: undefined,
          expected_own_points: net,
          transfer_hit_points: 0,
          moves,
        },
      },
    });
  }

  async function reloadWith(draft: unknown, confirmation: Record<string, unknown>) {
    open();
    await ready();
    await addRule("save_chips");
    cleanup();
    const [key, session] = savedSession();
    sessionStorage.setItem(
      key,
      JSON.stringify({
        ...session,
        draft,
        confirmation: { runId: "a".repeat(32), ...confirmation },
      }),
    );
    jobs.length = 0;
    open();
    await ready();
  }

  it.each([
    [1, false, false],
    [1, true, false],
    [3, false, false],
    [3, false, true],
    [3, true, false],
    [3, true, true],
  ] as const)(
    "gates priority editing and grouped admission for %i weeks with master=%s, three weeks=%s",
    async (window, master, threeWeek) => {
      releaseEnabled = master;
      threeWeekEnabled = threeWeek;
      const enabled = master && (window === 1 || threeWeek);
      bundlesOffered = true;
      intent.mockImplementation(() =>
        Response.json({
          status: "draft",
          draft: { window, hard: [], soft, max_total_cost_tenths: 15 },
        }),
      );
      open();
      await ready();
      await sendMessage("Prefer these players within a total allowance");
      await screen.findByText(en.understood);
      if (enabled) {
        expect(await screen.findByRole("spinbutton", { name: en.totalLimit })).toHaveValue(1.5);
        expect(screen.getAllByRole("combobox", { name: new RegExp(en.priority) })).toHaveLength(3);
      } else {
        expect(screen.queryByRole("spinbutton", { name: en.totalLimit })).toBeNull();
        expect(screen.queryByRole("combobox", { name: new RegExp(en.priority) })).toBeNull();
      }
      await userEvent.click(screen.getByRole("button", { name: en.compute }));
      if (enabled) {
        await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
        let request = jobs[0]!.compute.mock.calls[0]![0];
        expect(request.run?.stage).toBe("base");
        answer(jobs[0]!, request, 50, []);
        await waitFor(() => expect(jobs[1]!.compute).toHaveBeenCalledTimes(1));
        request = jobs[1]!.compute.mock.calls[0]![0];
        expect(request.run?.stage).toBe("followup");
        expect(request.preferenceBundle?.program?.preferences).toHaveLength(3);
        expect(jobs.slice(2).every((job) => !job.compute.mock.calls.length)).toBe(true);
      } else {
        await screen.findByText(en.individualLimitsOnly);
        expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();
        expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
        expect(savedSession()[1]).toMatchObject({ draft: { max_total_cost_tenths: 15 } });
      }
    },
  );

  it.each(["en", "tr"] as const)(
    "keeps a priority draft when changing windows until the member explicitly clears its unsupported settings in %s",
    async (language) => {
      bundlesOffered = true;
      const copy = LLMOPT_COPY[language];
      const hard = [{ kind: "save_chips" }];
      const preference = { kind: "include_player", player_id: OUTSIDER.id, max_cost_tenths: 10 };
      const draft = {
        hard,
        soft: [{ ...preference, priority: 2 }],
        max_total_cost_tenths: 15,
        window: 1,
      };
      intent.mockImplementation(() => Response.json({ status: "draft", draft }));
      open(language);
      await ready();
      await sendMessage("Prefer this player", language);
      await screen.findByText(copy.understood);
      const windowSelect = () => screen.getByRole("combobox", { name: copy.window });
      const clear = () => screen.getByRole("button", { name: copy.clearPrioritySettings });
      await userEvent.selectOptions(windowSelect(), "3");
      expect(await screen.findByText(copy.individualLimitsOnly)).toBeVisible();
      expect(savedSession()[1].draft).toEqual({ ...draft, window: 3 });
      await userEvent.selectOptions(windowSelect(), "1");
      expect(await screen.findByRole("spinbutton", { name: copy.totalLimit })).toHaveValue(1.5);
      expect(screen.getByRole("combobox", { name: new RegExp(copy.priority) })).toHaveValue("2");
      await userEvent.selectOptions(windowSelect(), "3");
      cleanup();
      open(language);
      await ready();
      await screen.findByText(copy.individualLimitsOnly);
      expect(screen.getByRole("button", { name: copy.compute })).toBeDisabled();
      await userEvent.click(clear());
      expect(savedSession()[1].draft).toEqual({ window: 3, hard, soft: [preference] });
      expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
      await userEvent.click(screen.getByRole("button", { name: copy.compute }));
      await waitFor(() => expect(jobs.some((job) => job.compute.mock.calls.length > 0)).toBe(true));
      for (const job of jobs)
        for (const [request] of job.compute.mock.calls) {
          expect(request.window).toBe(3);
          expect(request).not.toHaveProperty("run");
          expect(request).not.toHaveProperty("preferenceBundle");
        }
    },
  );

  it.each(["en", "tr"] as const)(
    "offers to clear reviewed settings after chat changes to a closed window in %s",
    async (language) => {
      bundlesOffered = true;
      const copy = LLMOPT_COPY[language];
      const reviewed = { kind: "keep_player", player_id: OWNED[0]!.player_id, priority: 1 };
      const soft = [{ ...reviewed, ...(language === "tr" ? { week: 2 } : {}) }];
      const initial = { window: 1, soft: [reviewed], hard: [], max_total_cost_tenths: 10 };
      const moved = { ...initial, window: 3, soft };
      intent.mockReturnValueOnce(Response.json({ status: "draft", draft: initial }));
      intent.mockReturnValueOnce(Response.json({ status: "draft", draft: moved }));
      open(language);
      await ready();
      await sendMessage(language === "tr" ? "Bu oyuncuyu tut" : "Keep this player", language);
      await screen.findByText(copy.understood);
      await sendMessage(
        language === "tr" ? "Onu ikinci hafta tut" : "Make it three weeks",
        language,
      );
      expect(await screen.findByText(copy.individualLimitsOnly)).toBeVisible();
      expect(screen.queryByText(copy.refusals.replyInvalid)).toBeNull();
      expect(screen.getByRole("button", { name: copy.compute })).toBeDisabled();
      const input = screen.getByRole("textbox", { name: copy.chat });
      await userEvent.type(input, "3");
      expect(screen.getByRole("button", { name: copy.send })).toBeDisabled();
      fireEvent.submit(input.closest("form")!);
      expect(intent).toHaveBeenCalledTimes(2);
      expect(savedSession()[1].draft).toEqual(moved);
      await userEvent.click(screen.getByRole("button", { name: copy.clearPrioritySettings }));
      expect(screen.getByRole("button", { name: copy.compute })).toBeEnabled();
      expect(screen.getByRole("button", { name: copy.send })).toBeEnabled();
      expect(savedSession()[1].draft).toEqual({
        window: 3,
        hard: [],
        soft: soft.map(({ priority: _priority, ...rule }) => rule),
      });
      expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
    },
  );

  it.each(["focus", "availability button"] as const)(
    "reopens a reviewed one-week draft on %s without reloading or submitting work",
    async (refresh) => {
      releaseEnabled = false;
      const draft = { hard: [], soft, max_total_cost_tenths: 15 };
      await reloadWith(draft, { wildcardNotHeld: false });
      const check = () => screen.getByRole("button", { name: en.checkPriorityAvailability });
      await screen.findByText(en.individualLimitsOnly);
      expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();
      releaseEnabled = true;
      bundlesOffered = true;
      if (refresh === "focus") fireEvent.focus(window);
      else await userEvent.click(check());
      await waitFor(() => expect(screen.queryByText(en.individualLimitsOnly)).toBeNull());
      expect(screen.getByRole("button", { name: en.compute })).toBeEnabled();
      expect(savedSession()[1].draft).toEqual(draft);
      expect(intent).not.toHaveBeenCalled();
      expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
    },
  );

  it("a restored priority run reads its saved preference result after rollback without admitting another stage", async () => {
    releaseEnabled = false;
    await reloadWith(
      { hard: [], soft, max_total_cost_tenths: 15 },
      { wildcardNotHeld: false, bundleMode: true, sending: true },
    );
    await waitFor(() => expect(jobs[0]!.readCached).toHaveBeenCalledTimes(1));
    answer(jobs[0]!, jobs[0]!.readCached.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(jobs[1]!.readCached).toHaveBeenCalledTimes(1));
    expect(
      jobs[1]!.readCached.mock.calls[0]![0].preferenceBundle?.program?.preferences,
    ).toHaveLength(3);
    expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
    expect(screen.getByText(en.individualLimitsOnly)).toBeVisible();
    expect(screen.getByRole("button", { name: en.compute })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: en.clearPrioritySettings }));
    expect(savedSession()[1].draft).toEqual({ hard: [], soft });
    expect(screen.queryByText(en.individualLimitsOnly)).toBeNull();
    expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
  });

  async function singlePrices(net: [number, number]) {
    const [base, first, second] = jobs as [FakeJob, FakeJob, FakeJob];
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    answer(base, base.readCached.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(second.compute).toHaveBeenCalledTimes(1));
    expect(jobs[3]!.compute).not.toHaveBeenCalled();
    answer(first, first.compute.mock.calls[0]![0], net[0]);
    expect(jobs[3]!.compute).not.toHaveBeenCalled();
    answer(second, second.compute.mock.calls[0]![0], net[1]);
  }

  for (const language of ["tr", "en"] as const) {
    it.each(["failed", "exhausted", "missing"] as const)(
      `keeps the base, both completed comparisons and requested preferences in ${language} when the preference plan is %s`,
      async (outcome) => {
        const copy = LLMOPT_COPY[language];
        bundlesOffered = true;
        intent.mockImplementation(() =>
          Response.json({
            status: "draft",
            draft: {
              hard: [],
              soft: [{ kind: "no_hits" }, { kind: "save_chips" }],
              comparison: { kind: "include_player", player_id: OUTSIDER.id, both: true },
              max_total_cost_tenths: 15,
            },
          }),
        );
        open(language);
        await ready();
        await sendMessage("Compare", language);
        await screen.findByText(copy.understood);
        await userEvent.click(screen.getByRole("button", { name: copy.compute }));
        await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
        answer(jobs[0]!, jobs[0]!.compute.mock.calls[0]![0], 50, []);
        await waitFor(() => expect(jobs[1]!.compute).toHaveBeenCalledTimes(1));
        const request = jobs[1]!.compute.mock.calls[0]![0];
        const bundle = request.preferenceBundle!;
        expect(bundle.slots).toHaveLength(2);
        const result = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
        const component = {
          status: "done" as const,
          payload: { ...result.payload },
          error_code: null,
        };
        result.payload.preference_bundle_result = {
          contract_version: "llmopt_preference_result_v1",
          request: bundle,
          components: [component, component],
          selected:
            outcome === "missing"
              ? null
              : {
                  status: outcome,
                  payload: null,
                  error_code: outcome === "exhausted" ? "RUN_BUDGET_EXHAUSTED" : "ADVICE_FAILED",
                },
          accepted: 0,
          applied: [],
          budget_exhausted: outcome === "exhausted",
        };
        act(() => jobs[1]!.show({ phase: "done", source: "api-cache", request, envelope: result }));
        for (const name of [copy.base, copy.with, copy.without]) {
          const ready = screen.getByRole("heading", { name }).closest("article");
          expect(ready).toHaveAttribute("data-plan-ready");
        }
        const summary = screen
          .getByRole("heading", { name: copy.combinedPlan })
          .closest("article")!;
        expect(summary).not.toHaveAttribute("data-plan-ready");
        expect(summary).toHaveTextContent(
          {
            failed: copy.combinedFailed,
            exhausted: copy.combinedExhausted,
            missing: copy.combinedMissing,
          }[outcome],
        );
        expect(summary).toHaveTextContent(copy.rules.no_hits);
        expect(summary).toHaveTextContent(copy.rules.save_chips);
        expect(summary.querySelector("[data-combined]")).toBeNull();
        expect(jobs.slice(2).every((job) => !job.compute.mock.calls.length)).toBe(true);
        await userEvent.click(
          screen.getByRole("button", { name: `${copy.remove} · ${copy.rules.save_chips}` }),
        );
        await userEvent.click(screen.getByRole("button", { name: copy.compute }));
        await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(2));
        expect(jobs[0]!.compute.mock.calls[1]![0].run?.run_id).not.toBe(request.run?.run_id);
      },
    );

    it(`can remove an orphaned total limit when prompted in ${language}`, async () => {
      const copy = LLMOPT_COPY[language];
      bundlesOffered = true;
      intent.mockImplementation(() =>
        Response.json({
          status: "draft",
          draft: { hard: [], soft: [{ kind: "no_hits" }], max_total_cost_tenths: 15 },
        }),
      );
      open(language);
      await ready();
      await sendMessage("Prefer", language);
      await screen.findByText(copy.understood);
      await userEvent.click(
        screen.getByRole("button", { name: `${copy.remove} · ${copy.rules.no_hits}` }),
      );
      await userEvent.click(screen.getByRole("button", { name: copy.compute }));
      expect(await screen.findByText(copy.totalUnavailable)).toBeVisible();
      expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
      await userEvent.clear(screen.getByRole("spinbutton", { name: copy.totalLimit }));
      expect(savedSession()[1].draft).not.toHaveProperty("max_total_cost_tenths");
      await userEvent.click(screen.getByRole("button", { name: copy.compute }));
      await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
    });
  }

  it("keeps the main plan and one sentence when the shared capacity refuses follow-ups", async () => {
    await reloadWith({ hard: [], soft }, { wildcardNotHeld: false });
    const [base, first, second, combined] = jobs as [FakeJob, FakeJob, FakeJob, FakeJob];
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    answer(base, base.readCached.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(second.compute).toHaveBeenCalledTimes(1));
    act(() => {
      for (const job of [first, second])
        job.show({
          phase: "failed",
          request: job.compute.mock.calls[0]![0],
          reason: "RUN_BUDGET_EXHAUSTED",
        });
    });
    expect(await screen.findAllByText(en.unfinishedPlans)).toHaveLength(1);
    expect(screen.getByRole("heading", { name: en.base })).toBeVisible();
    expect(combined.compute).not.toHaveBeenCalled();
    expect(screen.queryByText(en.priceUnavailable)).toBeNull();
  });

  it("starts once the single prices are in and applies every accepted rule and the one without a slot", async () => {
    await reloadWith({ hard: [], soft }, { wildcardNotHeld: false });
    await singlePrices([49, 48.5]);
    const combined = jobs[3]!;
    await waitFor(() => expect(combined.compute).toHaveBeenCalledTimes(1));
    const request = combined.compute.mock.calls[0]![0];
    expect(request.preferences).toMatchObject({
      no_hits: true,
      include_players: [OUTSIDER.id],
      max_hit_points: 4,
      net_points_priority: true,
    });
    expect(savedSession()[1]).toMatchObject({
      confirmation: { combined: [0, 1, 2], sending: true },
    });

    answer(combined, request, 47.6);
    const card = (await screen.findByRole("heading", { name: en.combinedPlan })).closest(
      "article",
    )!;
    expect(card).toHaveTextContent(en.combinedCost("2.4"));
    for (const label of labels) expect(card).toHaveTextContent(label);
    expect(card.querySelectorAll("[data-combined=applied]")).toHaveLength(3);
    expect(card.querySelectorAll("[data-combined=left-out]")).toHaveLength(0);
    expect(screen.getByText(en.priceCombined, { exact: true })).toBeVisible();
    expect(screen.queryByText(en.priceNotRun, { exact: true })).toBeNull();
  });

  it("names a rule above its limit as left out, and starts nothing for one accepted rule", async () => {
    const limited = [soft[0], { ...soft[1], max_cost_tenths: 10 }];
    await reloadWith({ hard: [], soft: limited }, { wildcardNotHeld: false });
    await singlePrices([49, 47]);
    expect(await screen.findByText(en.priceAboveCeiling, { exact: true })).toBeVisible();
    await waitFor(() =>
      expect(savedSession()[1]).toMatchObject({ confirmation: { combined: [] } }),
    );
    expect(jobs[3]!.compute).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: en.combinedPlan })).toBeNull();
  });

  it("names the rules it applies when they do not fit in one plan", async () => {
    await reloadWith({ hard: [], soft }, { wildcardNotHeld: false });
    await singlePrices([49, 48.5]);
    const combined = jobs[3]!;
    await waitFor(() => expect(combined.compute).toHaveBeenCalledTimes(1));
    combined.show({
      phase: "failed",
      request: combined.compute.mock.calls[0]![0],
      infeasibility: { repairs: [] },
    });
    const card = (await screen.findByRole("heading", { name: en.combinedPlan })).closest(
      "article",
    )!;
    expect(card).toHaveTextContent(en.combinedInfeasible);
    for (const label of labels) expect(card).toHaveTextContent(label);
  });

  it("names a rule that cannot sit beside the others as left out", async () => {
    // Rolling the transfer cannot be applied beside signing a player from outside the squad.
    const clash = [soft[0], soft[1], { kind: "hold_transfers" }];
    await reloadWith({ hard: [], soft: clash }, { wildcardNotHeld: false });
    await singlePrices([49, 48.5]);
    const combined = jobs[3]!;
    await waitFor(() => expect(combined.compute).toHaveBeenCalledTimes(1));
    expect(combined.compute.mock.calls[0]![0].preferences).not.toHaveProperty("hold_transfers");
    const card = (await screen.findByRole("heading", { name: en.combinedPlan })).closest(
      "article",
    )!;
    const leftOut = card.querySelectorAll("[data-combined=left-out]");
    expect(leftOut).toHaveLength(1);
    expect(leftOut[0]).toHaveTextContent(en.rules.hold_transfers);
    expect(screen.getByText(en.priceLeftOut, { exact: true })).toBeVisible();
  });

  it("a restored priority run reads its saved preference result after a failed capabilities read without admitting another stage", async () => {
    failCapabilitiesRead();
    bundlesOffered = true;
    await reloadWith(
      { hard: [], soft, max_total_cost_tenths: 15 },
      { wildcardNotHeld: false, bundleMode: true, sending: true },
    );
    await waitFor(() => expect(jobs[0]!.readCached).toHaveBeenCalledTimes(1));
    answer(jobs[0]!, jobs[0]!.readCached.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(jobs[1]!.readCached).toHaveBeenCalledTimes(1));
    expect(
      jobs[1]!.readCached.mock.calls[0]![0].preferenceBundle?.program?.preferences,
    ).toHaveLength(3);
    expect(jobs.every((job) => !job.compute.mock.calls.length)).toBe(true);
  });

  it("comes back after a reload, read when it was answered and asked again while sending", async () => {
    const saved = {
      runId: "a".repeat(32),
      wildcardNotHeld: false,
      followups: [{ kind: "priced" }, { kind: "priced" }],
      combined: [0, 1, 2],
    };
    await reloadWith({ hard: [], soft }, saved);
    const combined = jobs[3]!;
    expect(combined.readCached).not.toHaveBeenCalled();
    await waitFor(() => expect(jobs[0]!.readCached).toHaveBeenCalledTimes(1));
    answer(jobs[0]!, jobs[0]!.readCached.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(combined.readCached).toHaveBeenCalledTimes(1));
    expect(combined.compute).not.toHaveBeenCalled();
    expect(combined.readCached.mock.calls[0]![0].preferences).toMatchObject({
      include_players: [OUTSIDER.id],
      max_hit_points: 4,
    });
    expect(await screen.findByRole("heading", { name: en.combinedPlan })).toBeVisible();
    cleanup();

    const [key, session] = savedSession();
    sessionStorage.setItem(
      key,
      JSON.stringify({ ...session, confirmation: { ...saved, sending: true } }),
    );
    jobs.length = 0;
    open();
    await ready();
    await waitFor(() => expect(jobs[0]!.compute).toHaveBeenCalledTimes(1));
    expect(jobs[3]!.compute).not.toHaveBeenCalled();
    answer(jobs[0]!, jobs[0]!.compute.mock.calls[0]![0], 50, []);
    await waitFor(() => expect(jobs[3]!.compute).toHaveBeenCalledTimes(1));
    expect(jobs[3]!.resume).toHaveBeenCalledTimes(1);
    expect(jobs[3]!.compute.mock.calls[0]![0].preferences).toMatchObject({
      include_players: [OUTSIDER.id],
    });
  });
});

describe("the member's own model key", () => {
  const KEY = "sk-test-page-own-key-0001";
  const PROVIDER = "https://api.openai.com/v1/chat/completions";
  const words = en.ownKey;
  let provider: Mock<() => Response>;

  beforeEach(() => {
    provider = vi.fn(
      () =>
        new Response(
          JSON.stringify({
            choices: [{ finish_reason: "stop", message: { content: '{"status":"draft"}' } }],
          }),
        ),
    );
    const site = globalThis.fetch as unknown as Mock<typeof fetch>;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === `${ORIGIN}/api/v1/llmopt/prompt`)
          return new Response(
            JSON.stringify({
              system: "Read the member's instructions.",
              user: "{}",
              schema: { type: "object" },
              schema_name: "llmopt_intent",
              max_output_tokens: 1200,
            }),
          );
        if (url === PROVIDER) return provider();
        if (url === `${ORIGIN}/api/v1/llmopt/check`)
          return new Response(
            JSON.stringify({ status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } }),
          );
        return site(input, init);
      }),
    );
  });

  async function saveKey(model = "gpt-5-mini") {
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: words.model }), model);
    await user.type(screen.getByLabelText(words.key), KEY);
    await user.click(screen.getByRole("button", { name: words.save }));
  }

  it("reads the chat with the member's provider, keeps the key out of every store, and Delete deletes it", async () => {
    const watch = watchKeyLeaks(KEY);
    try {
      open("en", null);
      await ready();
      const key = screen.getByLabelText(words.key);
      // A text field drawn as dots: a browser offers to save what a password field held.
      expect(key).toHaveAttribute("type", "text");
      expect(key).toHaveAttribute("autocomplete", "off");
      expect(key).toHaveAttribute("spellcheck", "false");
      expect(screen.getByRole("button", { name: words.save })).toBeDisabled();
      await saveKey();

      const group = screen.getByRole("group", { name: words.title });
      expect(group).toHaveTextContent(words.providers.openai);
      expect(group).toHaveTextContent("gpt-5-mini");
      expect(screen.queryByLabelText(words.key)).toBeNull();
      expect(document.body.innerHTML).not.toContain(KEY);

      await sendMessage("No hits.");
      expect(
        await screen.findByRole("button", { name: `${en.remove} · ${en.rules.no_hits}` }),
      ).toBeVisible();
      expect(intent).not.toHaveBeenCalled();
      expect(provider).toHaveBeenCalledTimes(1);
      const fetch = globalThis.fetch as unknown as Mock;
      expect(requestsCarrying(fetch, KEY)).toEqual([PROVIDER]);
      expect(sentRequests(fetch).map(({ url }) => url)).toEqual(
        expect.arrayContaining([
          `${ORIGIN}/api/v1/llmopt/prompt`,
          PROVIDER,
          `${ORIGIN}/api/v1/llmopt/check`,
        ]),
      );
      expect(sessionStorage.length).toBeGreaterThan(0);
      expect(watch.leaks()).toEqual([]);

      await userEvent.click(screen.getByRole("button", { name: words.delete }));
      expect(heldModel()).toBeNull();
      expect(screen.getByLabelText(words.key)).toHaveValue("");
      expect(document.body.innerHTML).not.toContain(KEY);

      // With the key gone the chat is off again; nothing else reads it.
      expect(screen.getByRole("textbox", { name: en.chat })).toBeDisabled();
      expect(screen.getByText(words.needed)).toBeVisible();
      expect(provider).toHaveBeenCalledTimes(1);
      expect(watch.leaks()).toEqual([]);
    } finally {
      watch.restore();
    }
  });

  it("keeps the chat off until a key is held, with the rules still editable", async () => {
    open("en", null);
    await ready();
    expect(screen.getByText(words.needed)).toBeVisible();
    expect(screen.getByRole("textbox", { name: en.chat })).toBeDisabled();
    expect(screen.getByRole("button", { name: en.send })).toBeDisabled();
    expect(screen.getByRole("button", { name: en.add })).toBeEnabled();

    await saveKey();
    expect(screen.queryByText(words.needed)).toBeNull();
    // Save hands the keyboard to the chat, the next thing to do.
    expect(screen.getByRole("textbox", { name: en.chat })).toHaveFocus();
    const fetch = globalThis.fetch as unknown as Mock;
    expect(sentRequests(fetch).map(({ url }) => url)).not.toContain(
      `${ORIGIN}/api/v1/llmopt/intent`,
    );
  });

  it("deletes the key when the member leaves the page", async () => {
    const { unmount } = open("en", null);
    await ready();
    await saveKey();
    expect(heldModel()).toEqual({ provider: "openai", model: "gpt-5-mini" });
    unmount();
    expect(heldModel()).toBeNull();
  });

  it("moves focus to the form when the held key is deleted", async () => {
    open("en", null);
    await ready();
    await saveKey();
    await userEvent.click(screen.getByRole("button", { name: words.delete }));
    expect(screen.getByRole("combobox", { name: words.provider })).toHaveFocus();
  });

  it.each([
    [402, {}, en.refusals.accountRefused],
    [
      429,
      { error: { code: "insufficient_quota", type: "insufficient_quota" } },
      en.refusals.accountRefused,
    ],
  ] as const)(
    "names an account with no credit (%i) apart from a rate limit",
    async (status, body, line) => {
      provider.mockImplementation(() => new Response(JSON.stringify(body), { status }));
      open("en", null);
      await ready();
      await saveKey();
      await sendMessage("No hits.");
      expect(await screen.findByText(line, { exact: true })).toBeVisible();
    },
  );

  it("says the model stopped early when it ran into the reply limit", async () => {
    provider.mockImplementation(
      () =>
        new Response(
          JSON.stringify({ choices: [{ finish_reason: "length", message: { content: "" } }] }),
        ),
    );
    open("en", null);
    await ready();
    await saveKey();
    await sendMessage("No hits.");
    expect(await screen.findByText(en.refusals.replyCut, { exact: true })).toBeVisible();
  });

  it("names a key the provider refused without showing or logging the key", async () => {
    provider.mockImplementation(
      () =>
        new Response(JSON.stringify({ error: { message: `Incorrect API key provided: ${KEY}` } }), {
          status: 401,
        }),
    );
    const watch = watchKeyLeaks(KEY);
    try {
      open("en", null);
      await ready();
      await saveKey();
      await sendMessage("No hits.");
      expect(await screen.findByText(en.refusals.keyRefused, { exact: true })).toBeVisible();
      expect(document.body.innerHTML).not.toContain(KEY);
      expect(watch.leaks()).toEqual([]);
    } finally {
      watch.restore();
    }
  });

  it("waits out the provider's Retry-After with Send off", async () => {
    provider.mockImplementation(
      () => new Response("{}", { status: 429, headers: { "Retry-After": "2" } }),
    );
    open("en", null);
    await ready();
    await saveKey();
    await sendMessage("No hits.");
    expect(await screen.findByText(en.limitedFor(2), { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: en.send })).toBeDisabled();
  });

  it("asks for a base URL only for a local server, and only a loopback one", async () => {
    const user = userEvent.setup();
    open("en", null);
    await ready();
    expect(screen.queryByRole("textbox", { name: words.baseUrl })).toBeNull();
    await user.selectOptions(
      screen.getByRole("combobox", { name: words.provider }),
      words.providers.local,
    );
    const base = screen.getByRole("textbox", { name: words.baseUrl });
    await user.type(screen.getByRole("textbox", { name: words.model }), "llama3.1");
    await user.type(base, "https://example.com/v1");
    expect(screen.getByRole("button", { name: words.save })).toBeDisabled();
    await user.clear(base);
    await user.type(base, "http://localhost:11434/v1");
    await user.click(screen.getByRole("button", { name: words.save }));
    expect(heldModel()).toEqual({ provider: "local", model: "llama3.1" });
    expect(screen.getByRole("group", { name: words.title })).toHaveTextContent(
      words.providers.local,
    );
  });

  it("says once that a key it cannot hold is not valid, and clears it on the next edit", async () => {
    const user = userEvent.setup();
    open("en", null);
    await ready();
    await user.type(screen.getByRole("textbox", { name: words.model }), "two words");
    await user.type(screen.getByLabelText(words.key), KEY);
    await user.click(screen.getByRole("button", { name: words.save }));

    expect(heldModel()).toBeNull();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(words.invalid);
    expect(screen.getByRole("group", { name: words.title })).toContainElement(status);
    expect(screen.getByLabelText(words.key)).toHaveValue("");
    expect(document.body.innerHTML).not.toContain(KEY);

    await user.type(screen.getByRole("textbox", { name: words.model }), "x");
    expect(screen.queryByText(words.invalid)).toBeNull();
  });

  it("words the invalid key line in Turkish", () => {
    expect(LLMOPT_COPY.tr.ownKey.invalid).toBe("Anahtar, model ya da adres geçersiz.");
    expect(en.ownKey.invalid).toBe("The key, model or address is not valid.");
  });

  it("labels the form in Turkish", async () => {
    open("tr", null);
    await screen.findByRole("heading", { level: 1, name: LLMOPT_COPY.tr.title });
    const tr = LLMOPT_COPY.tr.ownKey;
    expect(screen.getByRole("group", { name: tr.title })).toBeVisible();
    expect(screen.getByRole("combobox", { name: tr.provider })).toBeVisible();
    expect(screen.getByRole("textbox", { name: tr.model })).toBeRequired();
    expect(screen.getByText(tr.needed)).toBeVisible();
    expect(screen.getByRole("button", { name: tr.save })).toBeVisible();
    expect(screen.getByRole("button", { name: tr.delete })).toBeVisible();
  });
});
