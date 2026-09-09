import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { readViewerEntry } from "../identity/useViewerEntry";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);
beforeEach(() => localStorage.clear());

describe.each(["tr", "en"] as const)("selected member controls in %s", (language) => {
  it("offers change and clear on a public member page without claiming that page", () => {
    const claimed = 35249001;
    const viewed = 35249002;
    const copy = MESSAGES[language].leagueMembers;
    localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: claimed }));
    render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/league/members/${viewed}`]}>
          <LeagueMemberView
            squad={mockEntrySquadEnvelopes[viewed]!}
            advice={mockEntryAdviceEnvelope(viewed, "saf-puan", 1)}
          />
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
    expect(screen.getByRole("link", { name: copy.backToMembers })).toBeInTheDocument();
  });
});
