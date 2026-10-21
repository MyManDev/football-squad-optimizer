import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, stubFetchByUrl } from "../../testSupport/fetchByUrl";
import { LeagueDataError } from "./dataErrors";
import { DIRECTORY_CONTRACT_VERSION, loadLeagueDirectory } from "./directory";

afterEach(() => vi.unstubAllGlobals());

const row = (leagueId: number) => ({
  league_id: leagueId,
  league_name: `League ${leagueId}`,
  season: "2026-27",
  gameweek: 8,
  path: `leagues/${leagueId}`,
});

function serve(leagues: unknown[]) {
  return stubFetchByUrl([
    [
      "/data/leagues.json",
      () => jsonResponse({ contract_version: DIRECTORY_CONTRACT_VERSION, payload: { leagues } }),
    ],
  ]);
}

describe("independent league directory rows", () => {
  it.each([null, { ...row(2), league_id: "2" }, { ...row(2), path: "../outside" }])(
    "keeps valid leagues when another row is invalid: %j",
    async (broken) => {
      const fetcher = serve([row(1), broken, row(3)]);
      const directory = await loadLeagueDirectory();
      expect(directory.leagues.map((league) => league.leagueId)).toEqual([1, 3]);
      expect(directory.leagues.map((league) => league.path)).toEqual(["leagues/1", "leagues/3"]);
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  it("quarantines duplicate identities without hiding an independent league", async () => {
    serve([row(1), row(2), { ...row(1), path: "leagues/other" }]);
    expect((await loadLeagueDirectory()).leagues.map((league) => league.leagueId)).toEqual([2]);
  });

  it.each([[null], [row(1), row(1)]])(
    "reports an unreadable directory when no usable record remains: %j",
    async (...rows) => {
      serve(rows);
      await expect(loadLeagueDirectory()).rejects.toBeInstanceOf(LeagueDataError);
    },
  );

  it("preserves an intentionally empty directory", async () => {
    serve([]);
    await expect(loadLeagueDirectory()).resolves.toEqual({ leagues: [] });
  });

  it("still refuses a different directory contract", async () => {
    stubFetchByUrl([
      [
        "/data/leagues.json",
        () => jsonResponse({ contract_version: "other", payload: { leagues: [row(1)] } }),
      ],
    ]);
    await expect(loadLeagueDirectory()).rejects.toBeInstanceOf(LeagueDataError);
  });
});
