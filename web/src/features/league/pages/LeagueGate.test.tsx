import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { jsonResponse, notFound, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import { memberAddress, membersAddress } from "../../../lib/leagueAddresses";
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
  writeChosenLeague(null);
});

/** A site from before the directory: no `leagues.json`, the one league under `data/league/`. */
function legacySite() {
  return stubFetchByUrl([
    ["/data/leagues.json", notFound],
    ["/data/league/members.json", () => jsonResponse(published)],
  ]);
}

/** Which addresses were asked for: the directory is read, a league's documents are not. */
const asked = (fetcher: ReturnType<typeof legacySite>) =>
  fetcher.mock.calls.map(([url]) => url.replace(/^.*\/data\//, "data/"));
const DIRECTORY_READS = ["data/leagues.json", "data/league/members.json"];

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location">{`${location.pathname}${location.search}`}</span>;
}
const location = () => screen.getByTestId("location").textContent;

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

  it("shows the entry form at an address from before the league number until the number is given", async () => {
    const fetcher = legacySite();
    open(language);
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Member page" })).toBeNull();
    expect(location()).toBe(`/league/members/${ENTRY}`);
    expect(fetcher).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));

    // The page the visitor asked for opens in place, under the league; no detour through
    // the members list.
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(location()).toBe(memberAddress(LEAGUE, ENTRY));
    expect(screen.queryByRole("heading", { name: "Members list" })).toBeNull();
    expect(readChosenLeague()).toBe(LEAGUE);
    expect(localStorage.getItem("squadopt.league")).toBe(String(LEAGUE));
  });

  it("rewrites an address from before the league number to the remembered league's", async () => {
    legacySite();
    writeChosenLeague(LEAGUE);
    open(language, `/league/members/${ENTRY}?mode=ortak-koru`);
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(location()).toBe(memberAddress(LEAGUE, ENTRY, "?mode=ortak-koru"));
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
  });

  it("opens the page at its league address, reading only the directory", async () => {
    const fetcher = legacySite();
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: copy.title })).toBeNull();
    expect(asked(fetcher)).toEqual(DIRECTORY_READS);
    // The league in the address is the one the visitor is in from here on.
    expect(readChosenLeague()).toBe(LEAGUE);
  });

  it("opens the page at its league address when another league is remembered", async () => {
    legacySite();
    writeChosenLeague(OTHER);
    open(language, memberAddress(LEAGUE, ENTRY));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    expect(readChosenLeague()).toBe(LEAGUE);
  });

  it("asks again, in place, when the address names a league the site does not publish", async () => {
    const fetcher = legacySite();
    writeChosenLeague(OTHER);
    open(language, memberAddress(OTHER, ENTRY));
    expect(await screen.findByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.label)).toHaveValue(String(OTHER));
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
