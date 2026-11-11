/** The shell as the app mounts it: the sidebar reads the visitor's identity from one place. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as navModule from "../design/shell/nav";
import { PHONE_QUERY } from "../design/shell/layout";
import { readMemberClaim } from "../features/league/identity/memberClaim";
import { writeChosenLeague } from "../features/league/identity/useChosenLeague";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { MESSAGES } from "../i18n/messages";
import { claimIn, forgetIdentity } from "../testSupport/league";
import { PILL_ENTRY, pillCalendar, pillSite } from "../testSupport/livePillSite";
import { IdentifiedShell } from "./IdentifiedShell";

const TR = MESSAGES.tr.shell;
const MEMBERS = "/league/352490/members";

beforeEach(() => {
  vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example");
  localStorage.clear();
  forgetIdentity();
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function LocationProbe() {
  const location = useLocation();
  return (
    <output
      data-testid="location"
      data-state={JSON.stringify(location.state)}
      data-search={location.search}
    >
      {location.pathname}
    </output>
  );
}

function open(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[path]}>
          <IdentifiedShell>
            <p>page</p>
          </IdentifiedShell>
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const sidebar = () => within(screen.getByRole("complementary", { name: TR.sidebar }));

describe("the identified shell", () => {
  it("keeps a standalone team free of another league's saved identity and tools", () => {
    claimIn();
    open("/entry/123");
    expect(sidebar().queryByText("Deniz Aral")).toBeNull();
    expect(sidebar().queryByRole("link", { name: TR.thisWeek })).toBeNull();
    expect(sidebar().getByRole("link", { name: TR.findLeague })).toHaveAttribute("href", "/");
    expect(readMemberClaim()?.entryId).toBe(35249001);
  });
  it("shows the claimed member in the sidebar and opens the league part of it", () => {
    claimIn();
    open("/fixtures");
    expect(sidebar().getByText("SquadOpt Classic League")).toBeInTheDocument();
    expect(sidebar().getByText("Deniz Aral")).toBeInTheDocument();
    expect(sidebar().getByText("North Stand Notes")).toBeInTheDocument();
    expect(sidebar().getByRole("link", { name: TR.league })).toHaveAttribute("href", MEMBERS);
    expect(sidebar().getByRole("link", { name: TR.thisWeek })).toHaveAttribute(
      "href",
      `${MEMBERS}/35249001`,
    );
  });

  it("drops the claim on Değiştir and asks again in the same league", async () => {
    claimIn();
    open("/fixtures");
    await userEvent.setup().click(sidebar().getByRole("button", { name: TR.changeMember }));
    expect(readMemberClaim()).toBeNull();
    const location = screen.getByTestId("location");
    expect(location).toHaveTextContent(MEMBERS);
    expect(location.dataset.state).toBe(JSON.stringify({ identity: "find" }));
    expect(sidebar().queryByRole("button", { name: TR.changeMember })).toBeNull();
    expect(sidebar().getByRole("link", { name: TR.findLeague })).toHaveAttribute("href", MEMBERS);
  });

  it("keeps this tab's identity when another tab chooses another league", () => {
    claimIn();
    open("/fixtures");
    act(() => {
      localStorage.setItem("squadopt.league", "7");
      window.dispatchEvent(new StorageEvent("storage", { key: "squadopt.league" }));
    });
    expect(sidebar().getByRole("link", { name: TR.league })).toHaveAttribute("href", MEMBERS);
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toMatchObject({
      leagueId: 352490,
      entryId: 35249001,
    });
  });

  it("asks who you are in the league of the address when the claim was made in another", () => {
    claimIn();
    open("/league/7/members");
    expect(sidebar().getByRole("link", { name: TR.findLeague })).toHaveAttribute(
      "href",
      "/league/7/members",
    );
    expect(sidebar().queryByRole("link", { name: TR.league })).toBeNull();
    expect(sidebar().queryByRole("button", { name: TR.changeMember })).toBeNull();
  });

  it("offers 'Ligini bul' to the form before any league, and the league's step after one", () => {
    const first = open("/fixtures");
    expect(sidebar().getAllByRole("link")[0]).toHaveTextContent(TR.findLeague);
    expect(sidebar().getByRole("link", { name: TR.findLeague })).toHaveAttribute("href", "/");
    first.unmount();
    writeChosenLeague(352490);
    open("/fixtures");
    expect(sidebar().getByRole("link", { name: TR.findLeague })).toHaveAttribute("href", MEMBERS);
    expect(sidebar().queryByRole("link", { name: TR.league })).toBeNull();
    expect(sidebar().queryByRole("link", { name: TR.thisWeek })).toBeNull();
  });
});

describe("the phone bar's LIVE pill", () => {
  /** A phone's viewport: jsdom answers no media query of its own. */
  function phone() {
    vi.stubGlobal("matchMedia", (query: string) => ({
      media: query,
      matches: query === PHONE_QUERY,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  }

  /** Real time passing, with React's work for it done. */
  const pause = (ms: number) =>
    act(async () => {
      await new Promise((resolve) => setTimeout(resolve, ms));
    });

  it("opens a team's own LIVE page on /entry, whoever is claimed in a league", async () => {
    phone();
    claimIn();
    pillSite(pillCalendar(3, 4, 30));
    open(`/entry/${PILL_ENTRY}`);
    const pill = await within(screen.getByRole("banner")).findByRole("link", { name: TR.live });
    expect(pill).toHaveAttribute("href", `/entry/${PILL_ENTRY}/live`);
  });

  it("opens the claimed member's own LIVE page anywhere else", async () => {
    phone();
    claimIn();
    pillSite(pillCalendar(3, 4, 30));
    open("/fixtures");
    const pill = await within(screen.getByRole("banner")).findByRole("link", { name: TR.live });
    expect(pill).toHaveAttribute("href", `${MEMBERS}/35249001/live`);
  });

  it("keeps LIVE as it is, its rival and all, and brings its top back when tapped there", async () => {
    phone();
    claimIn();
    pillSite(pillCalendar(3, 4, 30));
    const scroll = vi.fn();
    vi.stubGlobal("scrollTo", scroll);
    open(`${MEMBERS}/35249001/live?duel=35249005`);
    const pill = await within(screen.getByRole("banner")).findByRole("link", { name: TR.live });
    expect(pill).toHaveAttribute("aria-current", "page");
    scroll.mockClear();
    await userEvent.click(pill);
    const location = screen.getByTestId("location");
    expect(location).toHaveTextContent(`${MEMBERS}/35249001/live`);
    expect(location).toHaveAttribute("data-search", "?duel=35249005");
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ top: 0 }));
  });

  it("draws the shell no more once its documents have answered", async () => {
    phone();
    claimIn();
    pillSite(pillCalendar(3, 4, 30));
    const draws = vi.spyOn(navModule, "navItems");
    open("/fixtures");
    await within(screen.getByRole("banner")).findByRole("link", { name: TR.live });
    await pause(150);
    const settled = draws.mock.calls.length;
    await pause(150);
    // A loop of the window's clock would draw the shell again every millisecond.
    expect(draws.mock.calls.length).toBe(settled);
  });
});
