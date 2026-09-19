/**
 * Between a deadline and the next publish the page still shows the closed week's plan.
 * It has to say so, and it has to stop offering a computation nobody can apply.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const DEADLINE = "2026-09-18T17:30:00Z";

function renderView(deadlinePassed: string | null, language: "tr" | "en") {
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)}
          deadlinePassed={deadlinePassed}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("a member page whose gameweek has closed", () => {
  it("says the deadline passed, names the gameweek, and stops offering Compute", () => {
    for (const language of ["tr", "en"] as const) {
      const copy = COMPUTE_COPY[language];
      renderView(DEADLINE, language);
      expect(screen.getByText(copy.deadlinePassedTitle)).toBeInTheDocument();
      const notice = screen.getByTestId("deadline-passed");
      const gameweek = mockEntrySquadEnvelopes[ENTRY].payload.gameweek;
      expect(notice).toHaveTextContent(String(gameweek));
      expect(notice).toHaveTextContent("2026");
      expect(screen.getByText(copy.deadlinePassedCompute)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^(Hesapla|Compute)$/ })).toBeDisabled();
      cleanup();
    }
  });

  it("says nothing while the deadline is open or unknown", () => {
    renderView(null, "en");
    expect(screen.queryByTestId("deadline-passed")).toBeNull();
    expect(screen.queryByText(COMPUTE_COPY.en.deadlinePassedCompute)).toBeNull();
  });
});
