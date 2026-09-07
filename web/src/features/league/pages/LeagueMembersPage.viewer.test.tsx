/** The "which one is you" claim leads somewhere: the viewer's own page. */

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LeagueMembersView } from "./LeagueMembersPage";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

describe("the viewer claim on the members page", () => {
  it("links to the claimed member's own page", () => {
    const first = mockLeagueMembersEnvelope.payload.members.find(
      (member) => member.member_kind === "human",
    )!;
    window.localStorage.setItem("squadopt.viewer", JSON.stringify({ entryId: first.entry_id }));
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
