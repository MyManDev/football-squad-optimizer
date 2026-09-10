/** The "which one is you" claim leads somewhere: the viewer's own page. */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LeagueMembersView } from "./LeagueMembersPage";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { readViewerEntry, writeViewerEntry } from "../identity/useViewerEntry";

afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  writeViewerEntry(null);
});

describe("the viewer claim on the members page", () => {
  it("links to the claimed member's own page", () => {
    const first = mockLeagueMembersEnvelope.payload.members.find(
      (member) => member.member_kind === "human",
    )!;
    writeViewerEntry(first.entry_id);
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={["/league/members"]}>
          <LeagueMembersView envelope={mockLeagueMembersEnvelope} />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const link = screen.getByRole("link", { name: "Kadromu aç →" });
    expect(link).toHaveAttribute("href", `/league/members/${first.entry_id}`);
  });
});

function CurrentPath() {
  return <output aria-label="Current path">{useLocation().pathname}</output>;
}

function openMembers(language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/league/members"]}>
        <LeagueMembersView envelope={mockLeagueMembersEnvelope} />
        <CurrentPath />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const humanMembers = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);
const firstMember = humanMembers[0]!;
const secondMember = humanMembers[1]!;

describe.each(["tr", "en"] as const)("member selection in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;
  it("stores a selected row and navigates to its shareable member URL", () => {
    openMembers(language);
    const row = screen.getByRole("link", { name: firstMember.manager_name! }).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: copy.viewerSelect }));
    expect(readViewerEntry()).toEqual({
      entryId: firstMember.entry_id,
      verified: false,
      source: "self-selected",
    });
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      `/league/members/${firstMember.entry_id}`,
    );
  });

  it("keeps clear available for a saved member absent from the publication", () => {
    writeViewerEntry(99999999);
    openMembers(language);
    expect(screen.getByText(copy.viewerMissing)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.viewerChange })).toHaveAttribute(
      "href",
      "#league-member-list",
    );
    fireEvent.click(screen.getByRole("button", { name: copy.viewerClear }));
    expect(readViewerEntry()).toBeNull();
    expect(screen.queryByText(copy.viewerMissing)).not.toBeInTheDocument();
  });
});

it.each([null, firstMember.entry_id])(
  "ordinary public member links preserve claim %s",
  (claimed) => {
    if (claimed !== null) writeViewerEntry(claimed);
    openMembers();
    fireEvent.click(screen.getByRole("link", { name: secondMember.manager_name! }));
    expect(screen.getByLabelText("Current path")).toHaveTextContent(
      `/league/members/${secondMember.entry_id}`,
    );
    expect(readViewerEntry()?.entryId ?? null).toBe(claimed);
  },
);
