/**
 * The what-if mode's page under the member's page (#1132): offered where the plan on
 * screen is a solved week without a chip and the member's entry document carries the
 * device block, and otherwise saying there is nothing for the week; the panel reads the
 * capture's table through the page's loader only when the member starts.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const COPY = MESSAGES.tr.leagueMembers;
const BASE = mockEntrySquadEnvelopes[ENTRY]!;
const WITH_BLOCK: LeagueViewEnvelope<EntrySquad> = {
  ...BASE,
  payload: {
    ...BASE.payload,
    device_plan: fixture.members[0]!.entry as unknown as DevicePlanEntry,
  },
};
const EXAMPLE = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
// A solved week, as the published one-week documents state it.
const ADVICE = { ...EXAMPLE, payload: { ...EXAMPLE.payload, solver_status: "OPTIMAL" as const } };

function show(
  squad: LeagueViewEnvelope<EntrySquad>,
  advice: LeagueViewEnvelope<EntryAdvice>,
  loadDocument = vi.fn(),
) {
  render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}/what-if`]}>
        {withLeague(
          <LeagueMemberView
            squad={squad}
            advice={advice}
            members={mockLeagueMembersEnvelope.payload.members}
            index={mockEntryAdviceIndex(ENTRY).payload}
            whatIfDependencies={{ loadDocument }}
            tool="what-if"
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
  return loadDocument;
}

/** The panel's start button, or null where the page has nothing for the week. */
const tool = () => {
  const start = screen.queryByRole("button", { name: COPY.whatIfStart });
  if (start === null) expect(screen.getByText(COPY.toolEmpty)).toBeInTheDocument();
  return start;
};

describe("the what-if page", () => {
  it("is headed by its title and reads nothing until the member starts", () => {
    const loadDocument = show(WITH_BLOCK, ADVICE);
    expect(screen.getByRole("heading", { name: COPY.whatIfTitle })).toBeInTheDocument();
    expect(tool()).not.toBeNull();
    expect(loadDocument).not.toHaveBeenCalled();
  });

  it("reads the capture's table through the page's loader when the member starts", async () => {
    const loadDocument = vi.fn(async () => ({
      ...BASE,
      payload: fixture.document as unknown as DevicePlanDocument,
    }));
    show(WITH_BLOCK, ADVICE, loadDocument);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: COPY.whatIfStart }));
    });
    expect(loadDocument).toHaveBeenCalledTimes(1);
    // The example plan's players are not on the synthetic table, so the page says so.
    expect(await screen.findByText(COPY.whatIfOtherCapture)).toBeInTheDocument();
  });

  it("is not offered without the member's device block", () => {
    show(BASE, ADVICE);
    expect(tool()).toBeNull();
  });

  it("is not offered for a chip week, whose points are on another basis", () => {
    show(WITH_BLOCK, { ...ADVICE, payload: { ...ADVICE.payload, chip: "bboost" } });
    expect(tool()).toBeNull();
  });

  it.each([
    ["a plan over several weeks", { window: 3 as const }],
    [
      "a plan chosen with a Top 100 weight",
      { top100: { weight: 30 } as unknown as EntryAdvice["top100"] },
    ],
    [
      "a plan chosen with the manager's word",
      { evidence: {} as unknown as EntryAdvice["evidence"] },
    ],
  ])("is not offered for %s, whose points are on another basis", (_, patch) => {
    show(WITH_BLOCK, { ...ADVICE, payload: { ...ADVICE.payload, ...patch } });
    expect(tool()).toBeNull();
  });

  it("is not offered for a plan the solver did not prove", () => {
    show(WITH_BLOCK, {
      ...ADVICE,
      payload: { ...ADVICE.payload, solver_status: "UNKNOWN" as EntryAdvice["solver_status"] },
    });
    expect(tool()).toBeNull();
  });
});
