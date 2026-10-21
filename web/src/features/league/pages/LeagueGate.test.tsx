import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { jsonResponse, notFound, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import { memberAddress, membersAddress, PICK_HERE } from "../../../lib/leagueAddresses";
import { claimIn, forgetIdentity } from "../../../testSupport/league";
import { readMemberClaim } from "../identity/memberClaim";
import { readChosenLeague, writeChosenLeague } from "../identity/useChosenLeague";
import { LeagueGate } from "./LeagueGate";

const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };
const LEAGUE = published.payload.league_id;
const ENTRY = 35249001;
const OTHER = 123456;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  localStorage.clear();
  forgetIdentity();
});

/** A site from before the directory: no `leagues.json`, the one league under `data/league/`. */
function legacySite() {
  return stubFetchByUrl([
    ["/data/leagues.json", notFound],
    ["/data/league/members.json", () => jsonResponse(published)],
  ]);
}

/**
 * Which addresses were asked for: the directory is read, a league's documents are not. The
 * member step reads the member list too, which the loaders serve from the example under
 * test, so it asks the network for nothing here.
 */
const asked = (fetcher: ReturnType<typeof legacySite>) =>
  fetcher.mock.calls.map(([url]) => url.replace(/^.*\/data\//, "data/"));
const DIRECTORY_READS = ["data/leagues.json", "data/league/members.json"];

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{`${location.pathname}${location.search}`}</span>;
}
const location = () => screen.getByTestId("location").textContent;

/** Counts the stored league choice's writes from here on. */
function countLeagueChoices() {
  const heard = vi.fn();
  window.addEventListener("squadopt:league-changed", heard);
  return { heard, stop: () => window.removeEventListener("squadopt:league-changed", heard) };
}

function open(language: Language, address = `/league/members/${ENTRY}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page = (
    <LeagueGate>
      <h1>Member page</h1>
    </LeagueGate>
  );
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route path="/league/members/:entryId" element={page} />
            <Route path="/league/:leagueId/members/:entryId" element={page} />
            <Route path="/league/:leagueId/members" element={<h1>Members list</h1>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("league gate in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;
  const picker = MESSAGES[language].memberPicker;

  it("asks for the number, then who you are, at an address from before the number", async () => {
    const fetcher = legacySite();
    open(language);
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(location()).toBe(`/league/members/${ENTRY}`);
    expect(fetcher).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));

    // The address asked for is rewritten under the league, and the picker stands there
    // with focus on its question.
    const heading = await screen.findByRole("heading", { name: picker.title });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(location()).toBe(memberAddress(LEAGUE, ENTRY));
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(readChosenLeague()).toBe(LEAGUE);
    expect(localStorage.getItem("squadopt.league")).toBe(String(LEAGUE));

    // Once the visitor says who they are, the page opens where it was asked for.
    const group = await screen.findByRole("group", { name: picker.legend });
    await user.click(within(group).getByRole("radio", { name: /Deniz Aral/ }));
    await user.click(screen.getByRole("button", { name: picker.confirm }));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(location()).toBe(memberAddress(LEAGUE, ENTRY));
    expect(screen.queryByRole("heading", { name: "Members list" })).toBeNull();
  });

  it("rewrites an address from before the league number to the claimed member's league", async () => {
    legacySite();
    claimIn();
    open(language, `/league/members/${ENTRY}?mode=ortak-koru`);
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(location()).toBe(memberAddress(LEAGUE, ENTRY, "?mode=ortak-koru"));
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
  });

  it("rewrites the old address to the claim's league, not to a league chosen since", async () => {
    legacySite();
    claimIn();
    writeChosenLeague(OTHER);
    open(language, `/league/members/35249002`);
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(location()).toBe(memberAddress(LEAGUE, 35249002));
  });

  it("opens the page at its league address for a claimed visitor, reading only the directory", async () => {
    const fetcher = legacySite();
    claimIn();
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
    expect(asked(fetcher)).toEqual(DIRECTORY_READS);
    // The league in the address is the one the visitor is in from here on.
    expect(readChosenLeague()).toBe(LEAGUE);
  });

  it("asks who you are at a published league address, keeping the address", async () => {
    legacySite();
    writeChosenLeague(LEAGUE);
    open(language, memberAddress(LEAGUE, 35249003));
    expect(await screen.findByRole("heading", { name: picker.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(location()).toBe(memberAddress(LEAGUE, 35249003));
  });

  it("asks again, and drops the claim, when the address names another league than the claim's", async () => {
    legacySite();
    claimIn(ENTRY, OTHER);
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: picker.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(readMemberClaim()).toBeNull();
    expect(readChosenLeague()).toBe(LEAGUE);
  });

  it("chooses the league in the address once when another league is remembered", async () => {
    legacySite();
    writeChosenLeague(OTHER);
    const choices = countLeagueChoices();
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: picker.title })).toBeInTheDocument();
    expect(readChosenLeague()).toBe(LEAGUE);
    expect(choices.heard).toHaveBeenCalledTimes(1);
    choices.stop();
  });

  it("does not choose again when another tab chooses another league", async () => {
    legacySite();
    claimIn();
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    const choices = countLeagueChoices();
    act(() => {
      localStorage.setItem("squadopt.league", String(OTHER));
      window.dispatchEvent(new StorageEvent("storage", { key: "squadopt.league" }));
    });
    expect(choices.heard).not.toHaveBeenCalled();
    expect(localStorage.getItem("squadopt.league")).toBe(String(OTHER));
    expect(screen.getByRole("heading", { name: "Member page" })).toBeInTheDocument();
    choices.stop();
  });

  it("asks again, in place, when the address names a league the site does not publish", async () => {
    const fetcher = legacySite();
    writeChosenLeague(LEAGUE);
    open(language, memberAddress(OTHER, ENTRY));
    expect(await screen.findByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.label)).toHaveValue(String(OTHER));
    expect(screen.getByRole("status")).toHaveTextContent(copy.unsupported(OTHER));
    expect(readChosenLeague()).toBe(LEAGUE);
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(location()).toBe(memberAddress(OTHER, ENTRY));
    expect(asked(fetcher)).toEqual(DIRECTORY_READS);

    // The published league, given here, opens its members list: the address named
    // another league's member, who is not in this one.
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(copy.label));
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Members list" })).toBeInTheDocument();
    expect(location()).toBe(membersAddress(LEAGUE));
    expect(readChosenLeague()).toBe(LEAGUE);
  });

  it("reads the number as the links spell it: digits only", async () => {
    const fetcher = legacySite();
    open(language, `/league/0x${LEAGUE.toString(16)}/members/${ENTRY}`);
    expect(await screen.findByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(asked(fetcher)).toEqual([]);
  });

  it("says when the directory could not be read, and reads it again on request", async () => {
    let failures = 1;
    claimIn();
    const fetcher = stubFetchByUrl([
      ["/data/leagues.json", notFound],
      [
        "/data/league/members.json",
        () => (failures-- > 0 ? new Response("", { status: 503 }) : jsonResponse(published)),
      ],
    ]);
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByText(copy.directoryUnreadable)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: copy.retry }));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(asked(fetcher).filter((url) => url === "data/league/members.json")).toHaveLength(2);
  });

  it("says when nothing is published rather than asking for another league", async () => {
    stubFetchByUrl([
      ["/data/leagues.json", notFound],
      ["/data/league/members.json", notFound],
    ]);
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByText(copy.directoryMissing)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
  });

  it("keeps an unsupported number out of the gate", async () => {
    const fetcher = legacySite();
    open(language);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), "123");
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(screen.getByRole("status")).toHaveTextContent(copy.unsupported(123));
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(location()).toBe(`/league/members/${ENTRY}`);
    expect(readChosenLeague()).toBeNull();
    // Only the directory was read (by the gate, then by the form); nothing of league 123
    // was asked for.
    expect(asked(fetcher).every((url) => DIRECTORY_READS.includes(url))).toBe(true);
    expect(asked(fetcher)).toContain("data/league/members.json");
  });
});

/** A system page behind the two steps: its address names no league. */
function openVisitor(language: Language, address = "/moves?mode=garantici") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function StateProbe() {
    const location = useLocation();
    return (
      <span data-testid="visitor-location" data-state={JSON.stringify(location.state)}>
        {`${location.pathname}${location.search}`}
      </span>
    );
  }
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route
              path="/moves"
              element={
                <LeagueGate source="visitor">
                  <h1>Moves page</h1>
                </LeagueGate>
              }
            />
          </Routes>
          <StateProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("the system pages behind the two steps in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;
  const picker = MESSAGES[language].memberPicker;

  it("asks for the number with no league entered", () => {
    legacySite();
    openVisitor(language);
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Moves page" })).toBeNull();
  });

  it("keeps the address once the number connects, and asks who you are there", async () => {
    legacySite();
    openVisitor(language);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    const heading = await screen.findByRole("heading", { name: picker.title });
    // The navigation that carries the step state runs as a transition, so the picker can be
    // drawn once before it lands; wait for the state and for the focus it moves.
    await waitFor(() =>
      expect(screen.getByTestId("visitor-location").dataset.state).toBe(JSON.stringify(PICK_HERE)),
    );
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByTestId("visitor-location")).toHaveTextContent("/moves?mode=garantici");
    expect(readChosenLeague()).toBe(LEAGUE);

    const group = await screen.findByRole("group", { name: picker.legend });
    await user.click(within(group).getByRole("radio", { name: /Deniz Aral/ }));
    await user.click(screen.getByRole("button", { name: picker.confirm }));
    expect(await screen.findByRole("heading", { name: "Moves page" })).toBeInTheDocument();
    expect(screen.getByTestId("visitor-location")).toHaveTextContent("/moves?mode=garantici");
  });

  it("asks who you are in place with a league entered and nobody claimed", async () => {
    legacySite();
    writeChosenLeague(LEAGUE);
    openVisitor(language);
    expect(await screen.findByRole("heading", { name: picker.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Moves page" })).toBeNull();
    expect(screen.getByTestId("visitor-location")).toHaveTextContent("/moves?mode=garantici");
  });

  it("draws the page once the visitor has said who they are", async () => {
    legacySite();
    claimIn();
    openVisitor(language);
    expect(await screen.findByRole("heading", { name: "Moves page" })).toBeInTheDocument();
  });

  it("asks for the number again when the league entered is not published", async () => {
    legacySite();
    writeChosenLeague(OTHER);
    openVisitor(language);
    expect(await screen.findByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Moves page" })).toBeNull();
  });
});
