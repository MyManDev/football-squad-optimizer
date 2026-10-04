import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LeagueDataError, type LeagueTree } from "./data";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../fixtures/league";
import { useLeagueMemberData } from "./pages/useLeagueMemberData";
import { EXAMPLE_LEAGUE, stubTree, withLeague } from "../../testSupport/league";
import * as queries from "./queries";
import {
  CAPABILITIES_READ,
  LEAGUE_READ,
  leagueKeys,
  useEntrySquad,
  useLeagueScoreboard,
} from "./queries";

afterEach(() => {
  cleanup();
  focusManager.setFocused(undefined);
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const LEAGUE = EXAMPLE_LEAGUE.leagueId;

function withClient(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{withLeague(children)}</QueryClientProvider>
  );
}

/** Every production module of the league feature, with its "/" path relative to this folder. */
function leagueSources(directory: string = __dirname): { name: string; text: string }[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return leagueSources(path);
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    const name = relative(__dirname, path).split(sep).join("/");
    return [{ name, text: readFileSync(path, "utf-8") }];
  });
}

describe("league reads", () => {
  it("repeat no failed read, even under a client that would retry", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    const client = new QueryClient({ defaultOptions: { queries: { retry: 3, retryDelay: 0 } } });
    const { result } = renderHook(() => useLeagueScoreboard(), { wrapper: withClient(client) });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(LeagueDataError);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("read a failed document again as soon as a page that holds it is next opened", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    // The shipped client's defaults (app/App.tsx); nothing sets retryOnMount or refetchOnMount.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
    });
    const first = renderHook(() => useLeagueScoreboard(), { wrapper: withClient(client) });
    await waitFor(() => expect(first.result.current.isError).toBe(true));
    expect(fetch).toHaveBeenCalledOnce();
    first.unmount();
    // No clock moves: the one-minute stale time plays no part for a read that has no data.
    renderHook(() => useLeagueScoreboard(), { wrapper: withClient(client) });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("read no squad while there is no entry to read", () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useEntrySquad(null), { wrapper: withClient(client) });
    expect(result.current.fetchStatus).toBe("idle");
    expect(leagueKeys.entrySquad(LEAGUE, undefined)).toEqual(leagueKeys.entrySquad(LEAGUE, null));
  });

  it("refreshes stale capabilities on focus without recalculating or replacing the plan", async () => {
    expect(CAPABILITIES_READ).toEqual({ ...LEAGUE_READ, refetchOnWindowFocus: true });
    expect(CAPABILITIES_READ).not.toHaveProperty("refetchInterval");
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example");
    const entry = 35249001;
    const squad = mockEntrySquadEnvelopes[entry]!;
    const published = mockEntryAdviceEnvelope(entry, "saf-puan", 1);
    const readPublished = vi.fn<LeagueTree["entryAdvice"]>().mockResolvedValue(published);
    stubTree({
      members: vi.fn<LeagueTree["members"]>().mockResolvedValue(mockLeagueMembersEnvelope),
      entrySquad: vi.fn<LeagueTree["entrySquad"]>().mockResolvedValue(squad),
      entryAdviceIndex: vi
        .fn<LeagueTree["entryAdviceIndex"]>()
        .mockResolvedValue(mockEntryAdviceIndex(entry)),
      entryAdvice: readPublished,
    });
    let revision = "a".repeat(64);
    const fetched = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(
          JSON.stringify({
            contract_version: "league_capabilities_v1",
            league_id: squad.payload.league_id,
            capture_snapshot_id: squad.payload.source_snapshot_id,
            season: squad.payload.season,
            gameweek: squad.payload.gameweek,
            strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
            top100: { available: false, weights: [0] },
            managers_word: { available: false },
            decision_information: {
              version: "football_decision_information_v1",
              revision,
              source_snapshot_id: squad.payload.source_snapshot_id,
              observed_at: null,
              coach_news_bound: false,
              minute_components_bound: false,
            },
          }),
          { status: 200 },
        ),
    );
    vi.stubGlobal("fetch", fetched);
    const client = new QueryClient({
      defaultOptions: { queries: { refetchOnWindowFocus: false } },
    });
    const { result } = renderHook(
      () => useLeagueMemberData(String(entry), new URLSearchParams("mode=saf-puan&window=1")),
      { wrapper: withClient(client) },
    );
    await waitFor(() =>
      expect(result.current.capabilities?.decisionInformation?.revision).toBe(revision),
    );
    await waitFor(() => expect(result.current.advice.data).toEqual(published));
    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    expect(fetched).toHaveBeenCalledOnce();
    revision = "b".repeat(64);
    // Mark only the capabilities stale, without starting a refetch. The central
    // minute-long policy above determines when a real page reaches this state.
    await act(async () => {
      await client.invalidateQueries({
        queryKey: ["advice-capabilities", squad.payload.league_id],
        refetchType: "none",
      });
    });
    expect(fetched).toHaveBeenCalledOnce();
    await act(async () => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() =>
      expect(result.current.capabilities?.decisionInformation?.revision).toBe(revision),
    );
    expect(fetched).toHaveBeenCalledTimes(2);
    expect(
      fetched.mock.calls.every(
        ([url, init]) => String(url).endsWith("/capabilities") && (init?.method ?? "GET") === "GET",
      ),
    ).toBe(true);
    expect(readPublished).toHaveBeenCalledOnce();
    expect(result.current.advice.data).toEqual(published);
    client.clear();
  });

  it("are keyed and configured in one module", () => {
    const shared = [
      leagueKeys.members(LEAGUE)[0],
      leagueKeys.scoreboard(LEAGUE)[0],
      leagueKeys.entrySquad(LEAGUE, 1)[0],
    ];
    const offenders: string[] = [];
    let reads = 0;
    for (const { name, text } of leagueSources()) {
      // A `useQueries` call spreads the policy once, into the options every read it maps takes.
      const calls = text.match(/\buseQuer(?:y|ies)\(/g)?.length ?? 0;
      const policed = text.match(/\.\.\.(?:LEAGUE_READ|CAPABILITIES_READ)\b/g)?.length ?? 0;
      if (calls !== policed)
        offenders.push(`${name}: ${policed} of ${calls} reads use a central league read policy`);
      if (name === "queries.ts") continue;
      reads += calls;
      if (/\b(?:retry\s*:\s*(?:true|false|\d)|staleTime\s*:)/.test(text))
        offenders.push(`${name}: sets its own retry or staleTime`);
      for (const key of shared)
        if (text.includes(`"${key}"`)) offenders.push(`${name}: spells ${key}`);
    }
    expect(offenders).toEqual([]);
    expect(reads).toBeGreaterThan(0);
  });

  it("left outside LEAGUE_READ are named where the rule is written", () => {
    // The scan above counts `useQuery(` calls, so a read made through data/queries.ts (the
    // score pages' hooks) escapes it; queries.ts has to say which league modules do that.
    const rule = readFileSync(join(__dirname, "queries.ts"), "utf-8");
    const outside = leagueSources()
      .filter(({ text }) => /from\s+"(?:\.\.\/)+data\/queries"/.test(text))
      .map(({ name }) => name);
    expect(outside).toEqual(["pages/LeaguePage.tsx"]);
    expect(outside.filter((name) => !rule.includes(name))).toEqual([]);
  });

  it("are given to queries.ts in the member page's boundary document", () => {
    const boundaries = readFileSync(
      join(__dirname, "../../../../docs/architecture/member_page_boundaries.md"),
      "utf-8",
    );
    const rows = boundaries.split(/\r?\n/).filter((line) => line.startsWith("| `"));
    const owner = (row: string) => row.split("|")[1].trim();
    // Only queries.ts sets a retry or a stale time (the scan above), so only its row says so.
    expect(rows.filter((row) => /\bretry\b|\bstale/i.test(row)).map(owner)).toEqual([
      "`queries.ts`",
    ]);
    const row = rows.find((line) => owner(line) === "`queries.ts`") ?? "";
    for (const name of [...Object.keys(queries), ...Object.keys(leagueKeys)])
      expect(row).toContain(name);
  });
});
