/**
 * The duel on the member page (#1133): a closed tool until an address names a rival with
 * `?duel=`, which opens it; the page reads that rival's entry document of the same capture
 * and nothing else, an id outside the league's human members reads nothing, and a tap on
 * another rival changes the address in place.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { stubTree, withLeague } from "../../../testSupport/league";
import * as leagueData from "../data";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";

const ENTRY = 35249001;
const COPY = MESSAGES.tr.leagueMembers;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function view(
  search = "",
  duelSquad: LeagueViewEnvelope<EntrySquad> | null = mockEntrySquadEnvelopes[35249002]!,
) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}${search}`]}>
        {withLeague(
          <LeagueMemberView
            squad={mockEntrySquadEnvelopes[ENTRY]!}
            advice={null}
            members={mockLeagueMembersEnvelope.payload.members}
            duelSquad={duelSquad}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const tool = () =>
  screen.getByText(COPY.duelTitle, { selector: "summary span" }).closest("details")!;
const pressed = () =>
  within(tool())
    .getAllByRole("button", { pressed: true })
    .map((button) => button.textContent);

describe("the duel tool on the member page", () => {
  it("waits closed until an address names a rival", () => {
    const { container } = view("", null);
    expect(tool()).not.toHaveAttribute("open");
    expect(container.querySelector("[data-duel]")).toBeNull();
  });

  it("opens on an address that names a rival and sets the two elevens side by side", () => {
    const { container } = view("?duel=35249002");
    expect(tool()).toHaveAttribute("open");
    expect(pressed()).toEqual(["Half Space"]);
    expect(container.querySelector("[data-duel]")).toHaveAttribute("data-duel", "35249002");
  });

  it("changes the rival with one tap, and shows no board of the rival it left", () => {
    const { container } = view("?duel=35249002");
    fireEvent.click(within(tool()).getByRole("button", { name: "Late Flag FC" }));
    expect(pressed()).toEqual(["Late Flag FC"]);
    // The page holds the document of the rival it left until the new one is read.
    expect(container.querySelector("[data-duel]")).toBeNull();
  });

  it("ignores an id that is not one of the league's other human members", () => {
    const { container } = view(`?duel=${ENTRY}`);
    expect(tool()).not.toHaveAttribute("open");
    expect(within(tool()).queryAllByRole("button", { pressed: true })).toHaveLength(0);
    expect(container.querySelector("[data-duel]")).toBeNull();
  });
});

describe("the duel's read", () => {
  function page(search: string) {
    const entrySquad = vi
      .fn<leagueData.LeagueTree["entrySquad"]>()
      .mockImplementation(async (id) => {
        const squad = mockEntrySquadEnvelopes[id];
        if (!squad) throw new leagueData.LeagueDataMissing(`entries/${id}.json`);
        return squad;
      });
    stubTree({ entrySquad });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const rendered = render(
      <QueryClientProvider client={client}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}${search}`]}>
            {withLeague(
              <Routes>
                <Route path="/league/:leagueId/members/:entryId" element={<LeagueMemberPage />} />
              </Routes>,
            )}
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    return { ...rendered, entrySquad };
  }

  it("reads the named rival's entry document and shows the duel from it", async () => {
    const { container, entrySquad } = page("?duel=35249003");
    await waitFor(() =>
      expect(container.querySelector("[data-duel]")).toHaveAttribute("data-duel", "35249003"),
    );
    expect(entrySquad).toHaveBeenCalledWith(35249003);
  });

  it("reads no document for an id outside the league's human members", async () => {
    const { entrySquad } = page("?duel=99");
    await screen.findByText(COPY.duelTitle, { selector: "summary span" });
    expect(entrySquad.mock.calls.map(([id]) => id)).not.toContain(99);
  });
});
