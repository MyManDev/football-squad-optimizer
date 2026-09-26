import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LeagueDataError } from "./data";
import { leagueKeys, useEntrySquad, useLeagueScoreboard } from "./queries";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function withClient(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

/** Every production module of the league feature, with its path relative to this folder. */
function leagueSources(directory: string = __dirname): { name: string; text: string }[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return leagueSources(path);
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    return [{ name: relative(__dirname, path), text: readFileSync(path, "utf-8") }];
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

  it("read no squad while there is no entry to read", () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useEntrySquad(null), { wrapper: withClient(client) });
    expect(result.current.fetchStatus).toBe("idle");
    expect(leagueKeys.entrySquad(undefined)).toEqual(leagueKeys.entrySquad(null));
  });

  it("are keyed and configured in one module", () => {
    const shared = [
      leagueKeys.members()[0],
      leagueKeys.scoreboard()[0],
      leagueKeys.entrySquad(1)[0],
    ];
    const offenders: string[] = [];
    let reads = 0;
    for (const { name, text } of leagueSources()) {
      const calls = text.match(/\buseQuery\(/g)?.length ?? 0;
      const policed = text.match(/\.\.\.LEAGUE_READ\b/g)?.length ?? 0;
      if (calls !== policed)
        offenders.push(`${name}: ${policed} of ${calls} reads use LEAGUE_READ`);
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
});
