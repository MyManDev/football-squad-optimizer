/**
 * The switch for the manager's word is shown always and enabled only where the producer
 * solved it: disabled with the reason when no club news was read, disabled with a note
 * when the selection is not the one-week pure-points plan, and marked as example data
 * when the words came from the synthetic fixture.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { EntryAdviceIndex } from "../types";
import { EVIDENCE_COPY } from "./evidenceCopy";
import { MemberDecisionControls } from "./MemberDecisionControls";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;

const SOLVED: EntryAdviceIndex["evidence"] = {
  available: true,
  path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
  applied_count: 2,
  source_kind: "synthetic_fixture",
  source_label: "club_news_v1.fixture.json",
  clubs_covered: ["Arsenal", "Chelsea"],
  rule_version: "managers_word_rule_v1",
};

function renderControls(
  initial: string,
  evidence: EntryAdviceIndex["evidence"],
  language: "tr" | "en" = "tr",
) {
  const index = { ...mockEntryAdviceIndex(ENTRY).payload, evidence };
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <MemberDecisionControls entryId={ENTRY} members={MEMBERS} index={index} />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the manager's word switch", () => {
  it("is disabled with the reason when the publish read no club news", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, {
      available: false,
      reason: "no_evidence_this_run",
    });
    const box = screen.getByRole("checkbox", { name: /Kulübün sayfasının dediğini/ });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
    expect(screen.getByText(EVIDENCE_COPY.tr.unavailableReasons.no_evidence_this_run)).toBeTruthy();
  });

  it("switches the URL on and off where the producer solved it, and says it is example data", () => {
    const { container } = renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, SOLVED);
    const box = screen.getByRole("checkbox", { name: /Kulübün sayfasının dediğini/ });
    expect(box).toBeEnabled();
    expect(box).not.toBeChecked();
    expect(container.textContent).toContain(MESSAGES.tr.leagueMembers.exampleData);
    expect(container.textContent).toContain(EVIDENCE_COPY.tr.sourceExample);

    fireEvent.click(box);
    expect(screen.getByRole("checkbox", { name: /Kulübün sayfasının dediğini/ })).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /Kulübün sayfasının dediğini/ }));
    expect(screen.getByRole("checkbox", { name: /Kulübün sayfasının dediğini/ })).not.toBeChecked();
  });

  it("is disabled on a longer window with the note, in English too", () => {
    const { container } = renderControls(
      `/league/members/${ENTRY}?mode=saf-puan&window=3&llm=on`,
      SOLVED,
      "en",
    );
    const box = screen.getByRole("checkbox", { name: /Apply what the club's page said/ });
    expect(box).toBeDisabled();
    expect(box).not.toBeChecked();
    expect(container.textContent).toContain(EVIDENCE_COPY.en.onlyBaseline);
  });

  it("carries no probability wording in either language", () => {
    for (const language of ["tr", "en"] as const) {
      const { container, unmount } = renderControls(
        `/league/members/${ENTRY}?mode=saf-puan&window=1&llm=on`,
        SOLVED,
        language,
      );
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
      unmount();
    }
  });
});

describe("the manager's word switch, source and reason", () => {
  it("translates a member-level failure instead of printing the producer's text", () => {
    const { container } = renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, {
      available: false,
      reason: "not_solved_for_member",
    });
    expect(container.textContent).toContain(
      EVIDENCE_COPY.tr.unavailableReasons.not_solved_for_member,
    );
    expect(container.textContent).not.toContain("not_solved_for_member");
  });

  it("labels any source other than a club-news capture as example data", () => {
    const fixtureFile = { ...SOLVED, source_kind: "fixture_file" } as EntryAdviceIndex["evidence"];
    const { container, unmount } = renderControls(
      `/league/members/${ENTRY}?mode=saf-puan&window=1`,
      fixtureFile,
    );
    expect(container.textContent).toContain(MESSAGES.tr.leagueMembers.exampleData);
    expect(container.textContent).toContain(EVIDENCE_COPY.tr.sourceExample);
    unmount();

    const capture = { ...SOLVED, source_kind: "club_news_capture" } as EntryAdviceIndex["evidence"];
    const real = renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, capture);
    expect(real.container.textContent).not.toContain(MESSAGES.tr.leagueMembers.exampleData);
    expect(real.container.textContent).toContain(EVIDENCE_COPY.tr.sourceCapture);
  });
});
