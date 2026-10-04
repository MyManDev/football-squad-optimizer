import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { jsonResponse, notFound, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import { membersAddress } from "../../../lib/leagueAddresses";
import { writeChosenLeague } from "../identity/useChosenLeague";
import { readViewerEntry, writeViewerEntry } from "../identity/useViewerEntry";
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
  return <span data-testid="location">{location.pathname}</span>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  localStorage.clear();
  writeViewerEntry(null);
  // Each case is a first visit: no league remembered from the one before.
  writeChosenLeague(null);
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
  it("connects through published data without changing the existing viewer selection", async () => {
    const viewer = 35249001;
    writeViewerEntry({ leagueId: 352490, entryId: viewer });
    const fetcher = legacySite();
    open(language);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByLabelText(copy.label)).toHaveValue("");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(LEAGUE));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(membersAddress(LEAGUE));
    expect(readViewerEntry()?.entryId).toBe(viewer);
  });

  it("says what the site does before the field, and keeps the ID help folded", () => {
    open(language);
    const intro = screen.getByText(copy.intro);
    const field = screen.getByLabelText(copy.label);
    expect(intro.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const help = screen.getByText(copy.helpTitle).closest("details")!;
    expect(help.open).toBe(false);
    expect(help).toHaveTextContent(copy.help);
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
