/** The shell as the app mounts it: the sidebar reads the visitor's identity from one place. */

import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readMemberClaim } from "../features/league/identity/memberClaim";
import { writeChosenLeague } from "../features/league/identity/useChosenLeague";
import { LanguageProvider } from "../i18n/LanguageProvider";
import { MESSAGES } from "../i18n/messages";
import { claimIn, forgetIdentity } from "../testSupport/league";
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
});

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location" data-state={JSON.stringify(location.state)}>
      {location.pathname}
    </output>
  );
}

function open(path: string) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[path]}>
        <IdentifiedShell>
          <p>page</p>
        </IdentifiedShell>
        <LocationProbe />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const sidebar = () => within(screen.getByRole("complementary", { name: TR.sidebar }));

describe("the identified shell", () => {
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
