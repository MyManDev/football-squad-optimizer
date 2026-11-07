/**
 * The number a visitor gives: typed alone, or inside the game's own link pasted whole.
 */

import { describe, expect, it } from "vitest";

import { idIn } from "./fplId";

describe("the number in what the visitor gives", () => {
  it("takes a whole positive number, and nothing else typed alone", () => {
    expect(idIn(" 352490 ")).toBe(352490);
    expect(idIn("0")).toBeNull();
    expect(idIn("1e3")).toBeNull();
    expect(idIn("12.5")).toBeNull();
    expect(idIn("")).toBeNull();
  });

  it("reads a league's number out of its link, whatever follows it", () => {
    const link = "https://fantasy.premierleague.com/leagues/352490/standings/c?phase=1";
    expect(idIn(link)).toBe(352490);
    expect(idIn("fantasy.premierleague.com/leagues/352490")).toBe(352490);
    // A team's link is not a league's number.
    expect(idIn("https://fantasy.premierleague.com/entry/542322/event/10")).toBeNull();
  });

  it("reads a team's number out of its link, and not a league's", () => {
    expect(idIn("https://fantasy.premierleague.com/entry/542322/event/10", "entry")).toBe(542322);
    expect(idIn("https://fantasy.premierleague.com/entry/542322", "entry")).toBe(542322);
    expect(
      idIn("https://fantasy.premierleague.com/leagues/352490/standings/c", "entry"),
    ).toBeNull();
    expect(idIn("542322", "entry")).toBe(542322);
  });
});
