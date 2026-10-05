/** The browser state of a visitor who already opened the published league by its number. */
export const REMEMBERED_LEAGUE_KEY = "squadopt.league";
export const REMEMBERED_LEAGUE_ID = "352490";

export function rememberedLeague(origin: string) {
  return {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [{ name: REMEMBERED_LEAGUE_KEY, value: REMEMBERED_LEAGUE_ID }],
      },
    ],
  };
}

/** A first visitor: nothing remembered, every league address shows the entry form. */
export const NO_LEAGUE = { cookies: [], origins: [] };
