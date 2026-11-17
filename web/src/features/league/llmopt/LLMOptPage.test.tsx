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

let LLMOptPage: typeof Page;
let roster: "ok" | "fail";
let intent: Mock<(body: Record<string, unknown>) => Response>;
const clients: QueryClient[] = [];

beforeAll(async () => {
  vi.stubEnv("VITE_ADVICE_API_ORIGIN", ORIGIN);
  ({ LLMOptPage } = await import("./LLMOptPage"));
});

beforeEach(() => {
  jobs.length = 0;
  roster = "ok";
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
      if (url === `${ORIGIN}/api/v1/contributions/players`)
        return roster === "ok"
          ? new Response(JSON.stringify({ season: squad.season, players: ROSTER }))
          : new Response("{}", { status: 503 });
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
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
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
        deadline_utc: new Date(Date.now() + 86_400_000).toISOString(),
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
