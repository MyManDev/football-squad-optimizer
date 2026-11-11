/**
 * The phone bar's LIVE pill: the LIVE page's address while one of the member's matches is in
 * its window, else nothing, with nothing read outside a match window, the member's clubs read
 * from the documents the forwarded gate reads, nothing a page holds read again, and no render
 * of its own once the documents have answered.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  askedPaths,
  PILL_BUNDLE,
  PILL_ENTRY,
  PILL_TABLE,
  pillCalendar,
  pillEnvelope,
  pillMarked,
  pillSite,
} from "../../../testSupport/livePillSite";
import { FIXTURES_QUERY } from "../../fixtures/data";
import { loadLeagueDirectory } from "../directory";
import { forwardedKeys } from "../forwarded/reads";
import { leagueKeys } from "../queries";
import { memberClubs, useLivePill } from "./useLivePill";

afterEach(() => vi.unstubAllGlobals());

const TARGET = { entryId: PILL_ENTRY, to: `/league/314/members/${PILL_ENTRY}/live` };
const BUNDLE_KEY = forwardedKeys.bundle(PILL_ENTRY, PILL_TABLE.gameweek);

/** The hook in a fresh cache, counting its renders. */
function pill(target: typeof TARGET | null, enabled = true, client = new QueryClient()) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const count = { renders: 0 };
  const hook = renderHook(
    () => {
      count.renders += 1;
      return useLivePill(target, enabled);
    },
    { wrapper },
  );
  return { ...hook, count, client };
}

/** Real time passing, with React's work for it done. */
const pause = (ms: number) =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

describe("the member's clubs", () => {
  it("are the clubs of the live week's picks, by the table's names and the calendar's ids", () => {
    const read = { ok: true as const, copy: null, document: PILL_BUNDLE };
    expect([...memberClubs(read, PILL_TABLE, pillCalendar(9, 10, 30))!].sort()).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8,
    ]);
    // A calendar that does not name a pick's club cannot say them.
    expect(memberClubs(read, PILL_TABLE, pillCalendar(1, 2, 30, false))).toBeNull();
  });

  it("are not known from a bundle without the live week", () => {
    expect(
      memberClubs(
        { ok: true, copy: null, document: { ...PILL_BUNDLE, current_week: null } },
        PILL_TABLE,
        pillCalendar(1, 2, 30),
      ),
    ).toBeNull();
    expect(
      memberClubs({ ok: false, reason: "network" }, PILL_TABLE, pillCalendar(1, 2, 30)),
    ).toBeNull();
  });

  it("are not known from a bundle held from another week than the live one", () => {
    const read = { ok: true as const, copy: null, document: PILL_BUNDLE };
    const week = PILL_BUNDLE.current_week!.gameweek;
    expect(memberClubs(read, PILL_TABLE, pillCalendar(9, 10, 30), week)).not.toBeNull();
    expect(memberClubs(read, PILL_TABLE, pillCalendar(9, 10, 30), week + 1)).toBeNull();
  });
});

describe("the LIVE pill", () => {
  it("opens the member's LIVE page while one of their matches is played", async () => {
    const fetcher = pillSite(pillCalendar(3, 4, 30));
    const { result } = pill(TARGET);
    await waitFor(() => expect(result.current).toBe(TARGET.to));
    expect(askedPaths(fetcher)).toContain(`/api/v1/fpl/entry/${PILL_ENTRY}/bundle`);
  });

  it("stays away while only other clubs play, once the member's clubs are read", async () => {
    // Clubs 9 and 10 are none of the member's; clubs 1 to 8 played hours ago.
    let answer: (response: Response) => void = () => undefined;
    const bundle = new Promise<Response>((resolve) => {
      answer = resolve;
    });
    pillSite(pillCalendar(9, 10, 30), () => bundle);
    const { result, client } = pill(TARGET);
    await waitFor(() => expect(client.getQueryState(BUNDLE_KEY)?.fetchStatus).toBe("fetching"));
    // While the clubs are read the pill waits, whatever they turn out to be.
    expect(result.current).toBeNull();
    answer(pillMarked(PILL_BUNDLE));
    await waitFor(() => expect(client.getQueryState(BUNDLE_KEY)?.status).toBe("success"));
    await pause(20);
    expect(result.current).toBeNull();
  });

  it("reads nothing past the calendar while no match is in its window", async () => {
    const fetcher = pillSite(pillCalendar(3, 4, 400));
    const { result } = pill(TARGET);
    await waitFor(() => expect(askedPaths(fetcher)).toEqual(["/data/fixtures.json"]));
    await pause(50);
    expect(result.current).toBeNull();
    expect(askedPaths(fetcher)).toEqual(["/data/fixtures.json"]);
  });

  it("reads nothing where there is no phone bar or nobody to open", async () => {
    const fetcher = pillSite(pillCalendar(3, 4, 30));
    expect(pill(TARGET, false).result.current).toBeNull();
    expect(pill(null).result.current).toBeNull();
    await pause(50);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("counts every match of the week where the member's clubs cannot be read", async () => {
    pillSite(pillCalendar(9, 10, 30), () => pillMarked({ error: "upstream_unavailable" }, 503));
    const { result } = pill(TARGET);
    await waitFor(() => expect(result.current).toBe(TARGET.to));
  });

  it("reads none of the documents a page holds again, however old", async () => {
    const fetcher = pillSite(pillCalendar(3, 4, 30));
    const client = new QueryClient();
    // What a page read ten minutes ago: the calendar, the directory, the table and the bundle.
    const old = { updatedAt: Date.now() - 10 * 60_000 };
    client.setQueryData(FIXTURES_QUERY.queryKey, pillCalendar(3, 4, 30), old);
    vi.stubGlobal("fetch", fetcher);
    const directory = await loadLeagueDirectory();
    client.setQueryData(leagueKeys.directory(), directory, old);
    client.setQueryData(
      forwardedKeys.table(directory.leagues[0]!.devicePlan!),
      pillEnvelope(PILL_TABLE),
      old,
    );
    client.setQueryData(BUNDLE_KEY, { ok: true, copy: null, document: PILL_BUNDLE }, old);
    fetcher.mockClear();
    const { result } = pill(TARGET, true, client);
    await waitFor(() => expect(result.current).toBe(TARGET.to));
    await pause(20);
    expect(askedPaths(fetcher)).toEqual([]);
  });
});

describe("the pill's renders", () => {
  it.each([
    ["in a match window", pillCalendar(3, 4, 30), true],
    ["outside any window", pillCalendar(3, 4, 400), true],
    ["where there is no phone bar", pillCalendar(3, 4, 30), false],
  ] as const)("stop once its documents have answered, %s", async (_name, calendar, enabled) => {
    pillSite(calendar);
    const { count } = pill(TARGET, enabled);
    await pause(150);
    const settled = count.renders;
    await pause(150);
    // No render of its own: a loop of the window's clock would draw again every millisecond.
    expect(count.renders).toBe(settled);
    expect(settled).toBeLessThan(15);
  });
});
