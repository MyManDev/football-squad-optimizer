/** The viewer claim: held in memory during navigation, never an identity. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LeagueMembersView } from "../pages/LeagueMembersPage";
import { readViewerEntry, writeViewerEntry } from "./useViewerEntry";

afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  writeViewerEntry(null);
});

function renderMembers() {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={["/league/members"]}>
        <LeagueMembersView envelope={mockLeagueMembersEnvelope} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the viewer claim", () => {
  it("selecting a row stores the claim and shows it as a claim", () => {
    renderMembers();

    // The claim rule is stated before anyone selects: it is a claim, not a login.
    expect(screen.getByText("Hangisi sensin?")).toBeInTheDocument();

    const buttons = screen.getAllByRole("button", { name: "Bu benim" });
    fireEvent.click(buttons[0]);

    expect(screen.getByText("Sen")).toBeInTheDocument();
    const stored = readViewerEntry();
    expect(stored).not.toBeNull();
    expect(stored?.verified).toBe(false); // an assertion, deliberately not an identity
    expect(stored?.source).toBe("self-selected");
  });

  it("the claim survives a fresh render, and clearing removes it", () => {
    const first = renderMembers();
    fireEvent.click(screen.getAllByRole("button", { name: "Bu benim" })[0]);
    const claimed = readViewerEntry()?.entryId;
    first.unmount();

    renderMembers();
    expect(screen.getByText("Sen")).toBeInTheDocument();
    expect(readViewerEntry()?.entryId).toBe(claimed);

    fireEvent.click(screen.getByRole("button", { name: "Seçimi Kaldır" }));
    expect(readViewerEntry()).toBeNull();
    expect(screen.queryByText("Sen")).not.toBeInTheDocument();
  });

  it("previous stored selections are ignored", () => {
    window.localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: 35249001 }));
    expect(readViewerEntry()).toBeNull();
    window.localStorage.setItem("squadopt.viewer", "{broken json");
    expect(readViewerEntry()).toBeNull();
    window.localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: -4 }));
    expect(readViewerEntry()).toBeNull();
  });
});
