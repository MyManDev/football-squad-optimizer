import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { jsonResponse, notFound, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import {
  FIND_YOURSELF,
  memberAddress,
  membersAddress,
  PICK_HERE,
} from "../../../lib/leagueAddresses";
import { claimIn, forgetIdentity } from "../../../testSupport/league";
import { readMemberClaim } from "../identity/memberClaim";
import { readChosenLeague } from "../identity/useChosenLeague";
import { LeagueEntryPage } from "./LeagueEntryPage";

const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };
const LEAGUE = published.payload.league_id;

/** A site from before the directory: no `leagues.json`, the one league under `data/league/`. */
function legacySite() {
  return stubFetchByUrl([
    ["/data/leagues.json", notFound],
    ["/data/league/members.json", () => jsonResponse(published)],
  ]);
}

function LocationProbe() {
  const location = useLocation();
  return (
    <span data-testid="location" data-state={JSON.stringify(location.state)}>
      {location.pathname}
    </span>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  localStorage.clear();
  // Each case is a first visit: no league remembered from the one before, nobody claimed.
  forgetIdentity();
});

function open(language: Language) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<LeagueEntryPage />} />
          <Route path="/league/:leagueId/members" element={<h1>Member destination</h1>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("league entry in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;
  it("connects through published data and asks who you are on the members list", async () => {
    const fetcher = legacySite();
    open(language);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByLabelText(copy.label)).toHaveValue("");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
    const location = screen.getByTestId("location");
    expect(location).toHaveTextContent(membersAddress(LEAGUE));
    // After the step, the visitor's own page opens.
    expect(location.dataset.state).toBe(JSON.stringify(FIND_YOURSELF));
  });

  it("keeps the claim when the claimed league is entered again", async () => {
    claimIn(35249001, LEAGUE);
    legacySite();
    open(language);
    // The form offers the league the visitor is in.
    expect(screen.getByLabelText(copy.label)).toHaveValue(String(LEAGUE));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
    expect(readMemberClaim()?.entryId).toBe(35249001);
  });

  it("drops a claim made in another league when this one is entered", async () => {
    claimIn(35249001, 7);
    legacySite();
    open(language);
    const user = userEvent.setup();
    await user.clear(screen.getByLabelText(copy.label));
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
    expect(readMemberClaim()).toBeNull();
  });

  it("keeps the ID help folded", () => {
    const helpCopy = MESSAGES[language].fplIdHelp;
    open(language);
    const help = screen.getByText(helpCopy.title).closest("details")!;
    expect(help.open).toBe(false);
    expect(help).toHaveTextContent(helpCopy.league);
  });

  it("folds where the league ID is found between the field and its button", async () => {
    const helpCopy = MESSAGES[language].fplIdHelp;
    open(language);
    const field = screen.getByLabelText(copy.label);
    const help = screen.getByText(helpCopy.title).closest("details")!;
    const submit = screen.getByRole("button", { name: copy.submit });
    // Right under the field, inside its form, and before the form's one action.
    expect(help.parentElement).toBe(field.closest("form"));
    expect(help.previousElementSibling).toBe(field);
    expect(help.nextElementSibling).toBe(submit);
    // The field keeps its own label and description; the help is the next stop, not read
    // out with the field.
    expect(field).toHaveAccessibleName(copy.label);
    expect(field).toHaveAccessibleDescription(expect.stringContaining(copy.hint));
    expect(field).not.toHaveAccessibleDescription(expect.stringContaining(helpCopy.league));
    expect(help.querySelector("summary")).toHaveTextContent(helpCopy.title);
    expect(help.querySelector("code")).toHaveTextContent(
      "fantasy.premierleague.com/leagues/123456/standings/c",
    );
    await userEvent.setup().click(screen.getByText(helpCopy.title));
    expect(help.open).toBe(true);
  });

  it("validates decimal IDs before requesting any publication", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    open(language);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), "1e3");
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(screen.getByRole("status")).toHaveTextContent(copy.invalid);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["unsupported", "missing", "failed"] as const)(
    "states %s without changing routes",
    async (state) => {
      // The directory is read first; a site with none is one league, a 404 everywhere is
      // nothing published, and a 503 is a site that could not answer.
      const fetcher =
        state === "unsupported"
          ? legacySite()
          : stubFetchByUrl([
              [/./, () => new Response("", { status: state === "missing" ? 404 : 503 })],
            ]);
      open(language);
      const user = userEvent.setup();
      await user.type(
        screen.getByLabelText(copy.label),
        state === "unsupported" ? "123" : "352490",
      );
      await user.click(screen.getByRole("button", { name: copy.submit }));
      expect(
        await screen.findByText(state === "unsupported" ? copy.unsupported(123) : copy[state]),
      ).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
      expect(screen.getByTestId("location")).toHaveTextContent("/");
      if (state === "unsupported") {
        // Only the directory was read; nothing of league 123 was asked for.
        expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
          "/data/leagues.json",
          "/data/league/members.json",
        ]);
      }
    },
  );

  it("keeps the submitted ID fixed while its result is pending", async () => {
    // The directory read hangs until the test lets it answer; the league's record follows.
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.endsWith("/data/leagues.json")
          ? pending
          : Promise.resolve(
              url.endsWith("/data/league/members.json") ? jsonResponse(published) : notFound(),
            ),
      ),
    );
    open(language);
    const user = userEvent.setup();
    const field = screen.getByLabelText(copy.label);
    await user.type(field, String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(field).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.submit })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(copy.loading);
    await act(async () => finish(notFound()));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
  });
});

describe("the form in place", () => {
  function openInPlace(address: string, stay: boolean) {
    return render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route path="*" element={<LeagueEntryPage inPlace stay={stay} />} />
            <Route path="/league/:leagueId/members/:entryId" element={<h1>Member page</h1>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>,
    );
  }

  it("rewrites an address from before the number, asking the member step there", async () => {
    legacySite();
    openInPlace("/league/members/35249002", false);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(MESSAGES.tr.leagueEntry.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: MESSAGES.tr.leagueEntry.submit }));
    expect(await screen.findByRole("heading", { name: "Member page" })).toBeInTheDocument();
    const location = screen.getByTestId("location");
    expect(location).toHaveTextContent(memberAddress(LEAGUE, 35249002));
    // The step state is what puts focus on the picker's question when it stands there.
    await waitFor(() => expect(location.dataset.state).toBe(JSON.stringify(PICK_HERE)));
    // The gate at the new address chooses the league; a choice made here first would let
    // the gate rewrite the old address itself, dropping the step state.
    expect(readChosenLeague()).toBeNull();
  });

  it("keeps a system page's address with `stay`, asking the member step there", async () => {
    legacySite();
    openInPlace("/moves", true);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(MESSAGES.tr.leagueEntry.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: MESSAGES.tr.leagueEntry.submit }));
    const location = screen.getByTestId("location");
    await waitFor(() => expect(location.dataset.state).toBe(JSON.stringify(PICK_HERE)));
    expect(location).toHaveTextContent("/moves");
  });
});
