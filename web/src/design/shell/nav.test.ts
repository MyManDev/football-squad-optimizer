import { describe, expect, it } from "vitest";

import { memberAt, memberInContext, navItems, type Place } from "./nav";

const at = (pathname: string, search = "", hash = ""): Place => ({ pathname, search, hash });

const hrefs = (place: Place, member: ReturnType<typeof memberInContext>) =>
  navItems(place, member).map((item) => [item.key, item.to, item.active]);

describe("the sidebar's navigation", () => {
  it("opens the league entry page as 'Bu hafta' when no member is in context", () => {
    expect(hrefs(at("/"), null)).toEqual([
      ["thisWeek", "/", true],
      ["league", "/league/members", false],
      ["fixtures", "/fixtures", false],
      ["contribute", "/contribute", false],
    ]);
  });

  it("links 'Lig' to the member list and never to the system's league analysis", () => {
    for (const place of [at("/"), at("/league"), at("/league/members"), at("/admin")]) {
      const league = navItems(place, null).find((item) => item.key === "league")!;
      expect(league.to).toBe("/league/members");
    }
    expect(navItems(at("/league"), null).some((item) => item.active)).toBe(false);
    expect(navItems(at("/league/members"), null).find((item) => item.active)?.key).toBe("league");
  });

  it("keeps the member page's plan in 'Bu hafta' and points 'Kadro' at its squad", () => {
    const place = at("/league/members/35249001", "?mode=fark-yarat&window=3");
    const member = memberInContext(place, null, null);
    expect(hrefs(place, member)).toEqual([
      ["thisWeek", "/league/members/35249001?mode=fark-yarat&window=3", true],
      ["squad", "/league/members/35249001?mode=fark-yarat&window=3#kadro", false],
      ["league", "/league/members", false],
      ["fixtures", "/fixtures", false],
      ["contribute", "/contribute", false],
    ]);
    const squad = at("/league/members/35249001", "?mode=fark-yarat&window=3", "#kadro");
    expect(
      navItems(squad, member)
        .filter((item) => item.active)
        .map((item) => item.key),
    ).toEqual(["squad"]);
  });

  it("shows 'Kadro' only with a member in context", () => {
    expect(navItems(at("/fixtures"), null).map((item) => item.key)).not.toContain("squad");
    expect(
      navItems(at("/fixtures"), { entryId: "7", search: "" }).map((item) => item.key),
    ).toContain("squad");
  });

  it("does not treat the system's paper squad or a member's sub-page as the decision page", () => {
    expect(memberAt(at("/league/members/squadopt"))).toBeNull();
    expect(memberAt(at("/league/members"))).toBeNull();
    expect(memberAt(at("/league/members/12/history"))).toEqual({ entryId: "12", search: null });
    expect(memberAt(at("/league/members/12/"))).toEqual({ entryId: "12", search: "" });
    // On the history page 'Bu hafta' leads back to the member but is not the page itself.
    const history = at("/league/members/12/history");
    const items = navItems(history, memberInContext(history, null, null));
    expect(items[0]).toEqual({ key: "thisWeek", to: "/league/members/12", active: false });
  });

  it("falls back to the claimed member, then to the member page last opened", () => {
    const lastSeen = { entryId: "5", search: "?window=3" };
    expect(memberInContext(at("/fixtures"), 9, lastSeen)).toEqual({ entryId: "9", search: "" });
    expect(memberInContext(at("/fixtures"), 5, lastSeen)).toEqual(lastSeen);
    expect(memberInContext(at("/fixtures"), null, lastSeen)).toEqual(lastSeen);
    expect(memberInContext(at("/fixtures"), null, null)).toBeNull();
    // The address wins over both.
    expect(memberInContext(at("/league/members/3", "?mode=ortak-koru"), 9, lastSeen)).toEqual({
      entryId: "3",
      search: "?mode=ortak-koru",
    });
    // A history page returns to the plan last seen for that member only.
    expect(memberInContext(at("/league/members/5/history"), null, lastSeen)).toEqual(lastSeen);
    expect(memberInContext(at("/league/members/6/history"), null, lastSeen)).toEqual({
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
