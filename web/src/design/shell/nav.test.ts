import { describe, expect, it } from "vitest";

import { memberAt, memberInContext, navItems, type Place } from "./nav";

const LEAGUE = 352490;
const MEMBERS = `/league/${LEAGUE}/members`;

const at = (pathname: string, search = "", hash = ""): Place => ({ pathname, search, hash });

const hrefs = (
  place: Place,
  member: ReturnType<typeof memberInContext>,
  chosenLeagueId: number | null = null,
) => navItems(place, member, chosenLeagueId).map((item) => [item.key, item.to, item.active]);

describe("the sidebar's navigation", () => {
  it("opens the league entry page as 'Bu hafta' when no member is in context", () => {
    expect(hrefs(at("/"), null)).toEqual([
      ["thisWeek", "/", true],
      ["league", "/", false],
      ["fixtures", "/fixtures", false],
      ["contribute", "/contribute", false],
    ]);
  });

  it("links 'Lig' to the member list of the league in the address, never to the system's league analysis", () => {
    for (const place of [at(`/league/${LEAGUE}`), at(MEMBERS), at(`${MEMBERS}/35249001`)]) {
      const league = navItems(place, null).find((item) => item.key === "league")!;
      expect(league.to).toBe(MEMBERS);
    }
    expect(navItems(at(`/league/${LEAGUE}`), null).some((item) => item.active)).toBe(false);
    expect(navItems(at(MEMBERS), null).find((item) => item.active)?.key).toBe("league");
  });

  it("links 'Lig' to the chosen league's member list off a league address, and home with none", () => {
    for (const place of [at("/"), at("/admin"), at("/fixtures"), at("/league/members")]) {
      expect(navItems(place, null, LEAGUE).find((item) => item.key === "league")?.to).toBe(MEMBERS);
      expect(navItems(place, null).find((item) => item.key === "league")?.to).toBe("/");
    }
    // The league in the address wins over the chosen one.
    expect(
      navItems(at("/league/7/members"), null, LEAGUE).find((item) => item.key === "league")?.to,
    ).toBe("/league/7/members");
    expect(navItems(at("/"), null).find((item) => item.key === "league")?.active).toBe(false);
  });

  it("keeps the member page's plan in 'Bu hafta' and points 'Kadro' at its squad", () => {
    const place = at(`${MEMBERS}/35249001`, "?mode=fark-yarat&window=3");
    const member = memberInContext(place, null, null);
    expect(hrefs(place, member)).toEqual([
      ["thisWeek", `${MEMBERS}/35249001?mode=fark-yarat&window=3`, true],
      ["squad", `${MEMBERS}/35249001?mode=fark-yarat&window=3#kadro`, false],
      ["league", MEMBERS, false],
      ["fixtures", "/fixtures", false],
      ["contribute", "/contribute", false],
    ]);
    const squad = at(`${MEMBERS}/35249001`, "?mode=fark-yarat&window=3", "#kadro");
    expect(
      navItems(squad, member)
        .filter((item) => item.active)
        .map((item) => item.key),
    ).toEqual(["squad"]);
  });

  it("shows 'Kadro' only with a member in context, under the member's league", () => {
    expect(navItems(at("/fixtures"), null).map((item) => item.key)).not.toContain("squad");
    const items = navItems(at("/fixtures"), { leagueId: LEAGUE, entryId: "7", search: "" });
    expect(items.map((item) => item.key)).toContain("squad");
    expect(items.find((item) => item.key === "squad")?.to).toBe(`${MEMBERS}/7#kadro`);
    expect(items.find((item) => item.key === "league")?.to).toBe(MEMBERS);
  });

  it("does not treat the system's paper squad or a member's sub-page as the decision page", () => {
    expect(memberAt(at(`${MEMBERS}/squadopt`))).toBeNull();
    expect(memberAt(at(MEMBERS))).toBeNull();
    // The old shape without the league number names no member.
    expect(memberAt(at("/league/members/12"))).toBeNull();
    expect(memberAt(at(`${MEMBERS}/12/history`))).toEqual({
      leagueId: LEAGUE,
      entryId: "12",
      search: null,
    });
    expect(memberAt(at(`${MEMBERS}/12/`))).toEqual({ leagueId: LEAGUE, entryId: "12", search: "" });
    // On the history page 'Bu hafta' leads back to the member but is not the page itself.
    const history = at(`${MEMBERS}/12/history`);
    const items = navItems(history, memberInContext(history, null, null));
    expect(items[0]).toEqual({ key: "thisWeek", to: `${MEMBERS}/12`, active: false });
  });

  it("falls back to the claimed member in the chosen league, then to the member page last opened", () => {
    const lastSeen = { leagueId: LEAGUE, entryId: "5", search: "?window=3" };
    expect(memberInContext(at("/fixtures"), 9, lastSeen, LEAGUE)).toEqual({
      leagueId: LEAGUE,
      entryId: "9",
      search: "",
    });
    expect(memberInContext(at("/fixtures"), 5, lastSeen, LEAGUE)).toEqual(lastSeen);
    expect(memberInContext(at("/fixtures"), null, lastSeen, LEAGUE)).toEqual(lastSeen);
    expect(memberInContext(at("/fixtures"), null, null, LEAGUE)).toBeNull();
    // A claimed member with no chosen league has no address; the last page opened stands.
    expect(memberInContext(at("/fixtures"), 9, lastSeen)).toEqual(lastSeen);
    expect(memberInContext(at("/fixtures"), 9, null)).toBeNull();
    // The address wins over both.
    expect(
      memberInContext(at("/league/7/members/3", "?mode=ortak-koru"), 9, lastSeen, LEAGUE),
    ).toEqual({ leagueId: 7, entryId: "3", search: "?mode=ortak-koru" });
    // A history page returns to the plan last seen for that member only.
    expect(memberInContext(at(`${MEMBERS}/5/history`), null, lastSeen)).toEqual(lastSeen);
    expect(memberInContext(at(`${MEMBERS}/6/history`), null, lastSeen)).toEqual({
      leagueId: LEAGUE,
      entryId: "6",
      search: "",
    });
  });

  it("marks the fixtures and contribute pages as the current place", () => {
    expect(navItems(at("/fixtures"), null).find((item) => item.active)?.key).toBe("fixtures");
    expect(navItems(at("/contribute/"), null).find((item) => item.active)?.key).toBe("contribute");
    expect(navItems(at("/status"), null).some((item) => item.active)).toBe(false);
  });
});
