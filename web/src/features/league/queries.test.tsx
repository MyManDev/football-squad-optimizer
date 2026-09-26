import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LeagueDataError } from "./data";
import * as queries from "./queries";
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
