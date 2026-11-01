import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FIND_YOURSELF } from "../../lib/leagueAddresses";
import { memberAt, navItems, NO_IDENTITY, type Place, type ShellIdentity } from "./nav";

const LEAGUE = 352490;
const MEMBERS = `/league/${LEAGUE}/members`;
const OWN = `${MEMBERS}/35249001`;

beforeEach(() => vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example"));
afterEach(() => vi.unstubAllEnvs());

const at = (pathname: string, search = "", hash = ""): Place => ({ pathname, search, hash });

const CHOSEN: ShellIdentity = { leagueId: LEAGUE, member: null };
const CLAIMED: ShellIdentity = {
  leagueId: LEAGUE,
  member: {
    entryId: 35249001,
    league: "SquadOpt Classic League",
    name: "Deniz Aral",
    team: "North Stand Notes",
  },
};

const hrefs = (place: Place, identity: ShellIdentity, lastSeen = null) =>
  navItems(place, identity, lastSeen).map((item) => [item.key, item.to, item.active]);

describe("the sidebar's navigation with no league entered", () => {
  it("offers 'Ligini bul' to the form, then the fixtures and contribute pages", () => {
    expect(hrefs(at("/"), NO_IDENTITY)).toEqual([
      ["findLeague", "/", true],
      ["fixtures", "/fixtures", false],
      ["contribute", "/contribute", false],
    ]);
    expect(navItems(at("/fixtures"), NO_IDENTITY)[0]).toEqual({
      key: "findLeague",
      to: "/",
      active: false,
    });
    expect(navItems(at("/"), NO_IDENTITY).every((item) => item.state === undefined)).toBe(true);
  });

  it("omits Contribute with an empty origin, including on its old address", () => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "");
    for (const pathname of ["/", "/contribute", "/contribute/"]) {
      const items = navItems(at(pathname), NO_IDENTITY);
      expect(items.map((item) => item.key)).toEqual(["findLeague", "fixtures"]);
      expect(items.some((item) => item.to === "/contribute")).toBe(false);
    }
  });
});

describe("the sidebar's navigation with a league and nobody claimed", () => {
  it("sends 'Ligini bul' to the league's 'Sen kimsin?' step and renders no league items", () => {
    const items = navItems(at("/"), CHOSEN);
    expect(items[0]).toEqual({
      key: "findLeague",
      to: MEMBERS,
      state: FIND_YOURSELF,
      active: false,
    });
    expect(items.map((item) => item.key)).toEqual(["findLeague", "fixtures", "contribute"]);
    for (const key of ["thisWeek", "league"]) {
      expect(items.some((item) => item.key === key)).toBe(false);
    }
  });

  it("marks 'Ligini bul' as the place on that league's pages only", () => {
    for (const place of [at(`/league/${LEAGUE}`), at(MEMBERS), at(`${MEMBERS}/35249002`)]) {
      expect(navItems(place, CHOSEN)[0]!.active).toBe(true);
    }
    expect(navItems(at("/league/7/members"), CHOSEN)[0]!.active).toBe(false);
    expect(navItems(at("/fixtures"), CHOSEN)[0]!.active).toBe(false);
  });
});

describe("the sidebar's navigation with the member claimed", () => {
  it("opens the claimed member's page as 'Bu hafta', the league, the tools and the history", () => {
    expect(hrefs(at("/fixtures"), CLAIMED)).toEqual([
      ["thisWeek", OWN, false],
      ["league", MEMBERS, false],
      ["currentSquad", `${OWN}/current-squad`, false],
      ["whatIf", `${OWN}/what-if`, false],
      ["duel", `${OWN}/duel`, false],
      ["chips", `${OWN}/chips`, false],
      ["squadCard", `${OWN}/card`, false],
      ["history", `${OWN}/history`, false],
      ["fixtures", "/fixtures", true],
      ["contribute", "/contribute", false],
    ]);
    expect(navItems(at("/"), CLAIMED).some((item) => item.key === "findLeague")).toBe(false);
  });

  it("marks 'Bu hafta' on the own page, wherever on it the visitor reads", () => {
    const active = (place: Place) =>
      navItems(place, CLAIMED)
        .filter((item) => item.active)
        .map((item) => item.key);
    expect(active(at(OWN))).toEqual(["thisWeek"]);
    expect(active(at(OWN, "?mode=fark-yarat", "#kadro"))).toEqual(["thisWeek"]);
    expect(active(at(`${OWN}/`))).toEqual(["thisWeek"]);
    expect(active(at(`${OWN}/history`))).toEqual(["history"]);
  });

  it("keeps 'Bu hafta' on the visitor's own page while they read a rival's", () => {
    const items = navItems(at(`${MEMBERS}/35249002`, "?mode=agresif"), CLAIMED);
    expect(items.find((item) => item.key === "thisWeek")).toEqual({
      key: "thisWeek",
      to: OWN,
      active: false,
    });
    expect(items.some((item) => item.active)).toBe(false);
  });

  it("marks a tool on its own page only, and keeps the plan in its link", () => {
    const plan = "?mode=fark-yarat&window=3";
    const items = navItems(at(`${OWN}/duel`, plan), CLAIMED, {
      leagueId: LEAGUE,
      entryId: "35249001",
      search: plan,
    });
    expect(items.filter((item) => item.active).map((item) => item.key)).toEqual(["duel"]);
    expect(items.find((item) => item.key === "whatIf")?.to).toBe(`${OWN}/what-if${plan}`);
    expect(memberAt(at(`${OWN}/what-if`, plan))).toEqual({
      leagueId: LEAGUE,
      entryId: "35249001",
      search: plan,
    });
    expect(memberAt(at(`${OWN}/nothing-here`))).toBeNull();
  });

  it("marks 'Lig' on the member list only", () => {
    const league = (place: Place) => navItems(place, CLAIMED).find((item) => item.key === "league");
    expect(league(at(MEMBERS))?.active).toBe(true);
    expect(league(at(`/league/${LEAGUE}`))?.active).toBe(false);
    expect(league(at(`${MEMBERS}/35249002`))?.active).toBe(false);
  });

  it("keeps the plan last seen on the own page, and only for that member in that league", () => {
    const plan = "?mode=ortak-koru&window=3";
    const own = { leagueId: LEAGUE, entryId: "35249001", search: plan };
    expect(navItems(at("/fixtures"), CLAIMED, own)[0]!.to).toBe(`${OWN}${plan}`);
    expect(navItems(at("/fixtures"), CLAIMED, own)[2]!.to).toBe(`${OWN}/current-squad${plan}`);
    const rival = { leagueId: LEAGUE, entryId: "35249002", search: plan };
    expect(navItems(at("/fixtures"), CLAIMED, rival)[0]!.to).toBe(OWN);
    const elsewhere = { leagueId: 7, entryId: "35249001", search: plan };
    expect(navItems(at("/fixtures"), CLAIMED, elsewhere)[0]!.to).toBe(OWN);
  });
});

describe("the member an address is about", () => {
  it("does not treat the system's old address or a member's sub-page as the decision page", () => {
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
  });

  it("marks the fixtures and contribute pages as the current place", () => {
    expect(navItems(at("/fixtures"), NO_IDENTITY).find((item) => item.active)?.key).toBe(
      "fixtures",
    );
    expect(navItems(at("/contribute/"), NO_IDENTITY).find((item) => item.active)?.key).toBe(
      "contribute",
    );
    expect(navItems(at("/status"), NO_IDENTITY).some((item) => item.active)).toBe(false);
  });
});
