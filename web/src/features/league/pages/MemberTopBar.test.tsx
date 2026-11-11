/**
 * The member page's top bar leads to this member's LIVE page: under the league's address for
 * a league's member, and under /entry for a team on its own, where it is the only way there.
 * The tag follows the score bug, so it never stands between the team's name and its week.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { EXAMPLE_LEAGUE, withLeague } from "../../../testSupport/league";
import { MemberTopBar } from "./MemberTopBar";

afterEach(cleanup);

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;

function show(leagueId: number) {
  render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter>
        {withLeague(
          <MemberTopBar
            squad={SQUAD}
            members={mockLeagueMembersEnvelope.payload.members}
            fixtures={null}
            deadlinePassed={null}
          />,
          { ...EXAMPLE_LEAGUE, leagueId },
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
  return screen.getByRole("link", { name: MESSAGES.tr.shell.live });
}

describe("the top bar's way to LIVE", () => {
  it("opens a league member's LIVE page under the league's address", () => {
    expect(show(EXAMPLE_LEAGUE.leagueId)).toHaveAttribute(
      "href",
      `/league/${EXAMPLE_LEAGUE.leagueId}/members/${ENTRY}/live`,
    );
  });

  it("opens a team on its own at its /entry address", () => {
    expect(show(0)).toHaveAttribute("href", `/entry/${ENTRY}/live`);
  });

  it("follows the score bug, after the team's name and its week", () => {
    const link = show(EXAMPLE_LEAGUE.leagueId);
    const bar = link.closest("header")!;
    expect(bar.lastElementChild).toBe(link);
    expect(screen.getByRole("heading", { level: 1 }).compareDocumentPosition(link)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});
