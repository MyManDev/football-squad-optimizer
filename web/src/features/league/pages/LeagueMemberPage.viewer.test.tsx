import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { readViewerEntry, writeViewerEntry } from "../identity/useViewerEntry";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  writeViewerEntry(null);
});

describe.each(["tr", "en"] as const)("selected member controls in %s", (language) => {
  it("offers change and clear on a public member page without claiming that page", () => {
    const claimed = 35249001;
    const viewed = 35249002;
    const copy = MESSAGES[language].leagueMembers;
    writeViewerEntry(claimed);
    render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/league/members/${viewed}`]}>
          <Routes>
            <Route
              path="/league/members/:entryId"
              element={
                <LeagueMemberView
                  squad={mockEntrySquadEnvelopes[viewed]!}
                  advice={mockEntryAdviceEnvelope(viewed, "saf-puan", 1)}
                />
              }
            />
            <Route path="/league/members" element={<h1>{copy.title}</h1>} />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(readViewerEntry()?.entryId).toBe(claimed);
    expect(screen.getByText(copy.viewerBody)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.viewerChange })).toHaveAttribute(
      "href",
      "/league/members",
    );
    fireEvent.click(screen.getByRole("button", { name: copy.viewerClear }));
    expect(readViewerEntry()).toBeNull();
    expect(screen.queryByRole("button", { name: copy.viewerClear })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
  });
});
