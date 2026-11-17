import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { stubTree, withLeague } from "../../../testSupport/league";
import type { AdviceRequest } from "../advice/adviceClient";
import type { ComputePhase } from "../advice/useAdviceJob";
import { FIXTURES_QUERY } from "../../fixtures/data";
import { LLMOPT_COPY } from "./copy";
import type { LLMOptPage as Page } from "./LLMOptPage";

interface FakeJob {
  compute: Mock<(request: AdviceRequest) => void>;
  resume: Mock<(request: AdviceRequest) => boolean>;
  readCached: Mock<(request: AdviceRequest) => void>;
  reset: Mock<() => void>;
  show: (state: ComputePhase) => void;
}

// The page's three advice jobs, in the order each render mounted them.
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

let LLMOptPage: typeof Page;
let roster: "ok" | "fail" | "late";
let releaseRoster: () => void;
let rosterGate: Promise<void>;
let intent: Mock<(body: Record<string, unknown>) => Response>;
const clients: QueryClient[] = [];

beforeAll(async () => {
  vi.stubEnv("VITE_ADVICE_API_ORIGIN", ORIGIN);
  ({ LLMOptPage } = await import("./LLMOptPage"));
});

beforeEach(() => {
  jobs.length = 0;
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
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === `${ORIGIN}/api/v1/contributions/players`) {
        if (roster === "fail") return new Response("{}", { status: 503 });
        if (roster === "late") await rosterGate;
        return new Response(JSON.stringify({ season: squad.season, players: ROSTER }));
      }
      if (url === `${ORIGIN}/api/v1/llmopt/intent`)
        return intent(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Opens the page the way a visit or a reload does: a fresh query cache, the tab's storage kept. */
function open(language: "en" | "tr" = "en") {
  // The fixtures are set, not read, so the cache keeps them while no page observes them.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  client.setQueryData(FIXTURES_QUERY.queryKey, {
    season: squad.season,
    source_snapshot_id: "fixtures",
    captured_at_utc: "2026-01-01T00:00:00Z",
    current_gameweek: squad.gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: squad.gameweek,
        deadline_utc: DEADLINE,
        fixtures: [],
      },
    ],
  });
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/entry/${ENTRY}/llmopt`]}>
          {withLeague(
            <Routes>
              <Route path="/entry/:entryId/llmopt" element={<LLMOptPage />} />
            </Routes>,
          )}
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

async function ready() {
  return screen.findByRole("heading", { level: 1, name: en.title });
}

async function sendMessage(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: en.chat }), text);
  const send = screen.getByRole("button", { name: en.send });
  await waitFor(() => expect(send).toBeEnabled());
  await user.click(send);
}

describe("chat refusals", () => {
  it.each([
    [503, "LLMOPT_DISABLED", en.refusals.disabled],
    [503, "LLMOPT_UNAVAILABLE", en.refusals.busy],
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

  async function reloadConfirmed(confirmation: Record<string, unknown>) {
    open();
    await ready();
    await addRule("hold_transfers");
    cleanup();
    const [key, session] = savedSession();
    sessionStorage.setItem(key, JSON.stringify({ ...session, confirmation }));
    jobs.length = 0;
    open();
    await ready();
    return jobs[0]!;
  }

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

  it("reads, without sending again, a run whose requests were all answered", async () => {
    const base = await reloadConfirmed({ wildcardNotHeld: false });
    await waitFor(() => expect(base.readCached).toHaveBeenCalledTimes(1));
    expect(base.compute).not.toHaveBeenCalled();
  });
});
