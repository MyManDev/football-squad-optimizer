import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import * as leagueData from "../data";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";

const ENTRY = 35249001;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function memberSurface(
  squad: LeagueViewEnvelope<EntrySquad>,
  language: Language = "en",
  advice: LeagueViewEnvelope<EntryAdvice> | null = null,
) {
  const entryId = squad.payload.entry.entry_id;
  return (
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${entryId}`]}>
        <LeagueMemberView
          squad={squad}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={mockEntryAdviceIndex(entryId).payload}
        />
      </MemoryRouter>
    </LanguageProvider>
  );
}

function sectionFor(title: string): HTMLElement {
  const section = screen.getByRole("heading", { level: 2, name: title }).closest("section");
  if (!section) throw new Error(`No section for ${title}`);
  return section;
}

describe("the member's published squad", () => {
  it.each(["tr", "en"] as const)("shows the entry's XI, captain and bench in %s", (language) => {
    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    const copy = MESSAGES[language];
    render(memberSurface(squad, language));

    const pitch = screen.getByRole("list", { name: copy.squad.pitchLabel });
    expect(
      within(pitch)
        .getAllByRole("listitem")
        .map((row) => row.getAttribute("aria-label")),
    ).toEqual(["GK", "DEF", "MID", "FWD"]);
    for (const player of squad.payload.starting_xi) {
      expect(within(pitch).getByTitle(player.name)).toHaveTextContent(player.short_name);
    }
    expect(screen.getByText(copy.leagueMembers.starterCount(11))).toBeInTheDocument();
    const captain = squad.payload.starting_xi.find((player) => player.is_captain)!;
    const captainChip = within(pitch).getByLabelText(copy.squad.captainLabel).parentElement!;
    expect(within(captainChip).getByTitle(captain.name)).toBeInTheDocument();
    expect(within(pitch).getAllByLabelText(copy.squad.captainLabel)).toHaveLength(1);
    const bench = sectionFor(copy.leagueMembers.bench);
    expect(Array.from(bench.querySelectorAll("strong"), (player) => player.textContent)).toEqual(
      squad.payload.bench.map((player) => player.name),
    );
    expect(within(bench).getByText(copy.leagueMembers.benchCount(4))).toBeInTheDocument();
  });

  it("changes the held players when the displayed member changes", () => {
    const first = mockEntrySquadEnvelopes[ENTRY]!;
    const second = mockEntrySquadEnvelopes[35249002]!;
    const firstOnly = first.payload.starting_xi.find(
      (player) => !second.payload.starting_xi.some((other) => other.player_id === player.player_id),
    )!;
    expect(firstOnly).toBeDefined();
    const page = render(memberSurface(first));
    expect(screen.getByTitle(firstOnly.name)).toBeInTheDocument();

    page.rerender(memberSurface(second));

    const pitch = screen.getByRole("list", { name: MESSAGES.en.squad.pitchLabel });
    expect(within(pitch).queryByTitle(firstOnly.name)).not.toBeInTheDocument();
    for (const player of second.payload.starting_xi) {
      expect(within(pitch).getByTitle(player.name)).toBeInTheDocument();
    }
    const bench = sectionFor(MESSAGES.en.leagueMembers.bench);
    expect(Array.from(bench.querySelectorAll("strong"), (player) => player.textContent)).toEqual(
      second.payload.bench.map((player) => player.name),
    );
  });

  it("uses published bench order without changing the payload or inventing an absent order", () => {
    const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    const original = squad.payload.bench;
    squad.payload.bench = [
      original[2]!,
      { ...original[1]!, bench_order: null },
      original[0]!,
      original[3]!,
    ];
    const before = squad.payload.bench.map((player) => player.player_id);
    Object.freeze(squad.payload.bench);
    render(memberSurface(squad));

    const bench = sectionFor(MESSAGES.en.leagueMembers.bench);
    const names = Array.from(bench.querySelectorAll("strong"));
    expect(names.map((player) => player.textContent)).toEqual([
      original[0]!.name,
      original[2]!.name,
      original[3]!.name,
      original[1]!.name,
    ]);
    expect(names.map((player) => player.parentElement!.firstElementChild!.textContent)).toEqual([
      "1",
      "3",
      "4",
      "—",
    ]);
    expect(squad.payload.bench.map((player) => player.player_id)).toEqual(before);
  });

  it.each(["tr", "en"] as const)(
    "keeps the unpublished held vice-captain separate from the proposed one in %s",
    (language) => {
      const squad = mockEntrySquadEnvelopes[ENTRY]!;
      const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
      const proposedVice = advice.payload.vice_captain!;
      expect(proposedVice).not.toBeNull();
      proposedVice.name = "Proposed Vice Only";
      proposedVice.short_name = "Proposed Vice Only";
      render(memberSurface(squad, language, advice));

      const held = sectionFor(MESSAGES[language].leagueMembers.memberSquad);
      expect(
        within(held).getByText(MESSAGES[language].leagueMembers.heldViceCaptainUnavailable),
      ).toBeInTheDocument();
      expect(held).not.toHaveTextContent("Proposed Vice Only");
      expect(screen.getAllByText("Proposed Vice Only").length).toBeGreaterThan(0);
    },
  );

  it.each(["tr", "en"] as const)("shows absent squad data as unavailable in %s", (language) => {
    const copy = MESSAGES[language];
    render(memberSurface(mockEntrySquadEnvelopes[35249010]!, language));

    expect(screen.getByText(copy.leagueMembers.emptySquad)).toBeInTheDocument();
    expect(screen.getByText(copy.leagueMembers.emptySquadBody)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: copy.squad.pitchLabel })).not.toBeInTheDocument();
    expect(screen.queryByText(copy.leagueMembers.starterCount(0))).not.toBeInTheDocument();
    expect(screen.queryByText(copy.leagueMembers.benchCount(0))).not.toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "shows a missing member document as unavailable rather than an empty team in %s",
    async (language) => {
      const copy = MESSAGES[language];
      vi.spyOn(leagueData, "loadEntrySquad").mockRejectedValue(
        new leagueData.LeagueDataMissing(`entries/${ENTRY}.json`),
      );
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={client}>
          <LanguageProvider initialLanguage={language}>
            <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
              <Routes>
                <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
              </Routes>
            </MemoryRouter>
          </LanguageProvider>
        </QueryClientProvider>,
      );

      expect(await screen.findByText(copy.leagueMembers.entryNotAvailable)).toBeInTheDocument();
      expect(screen.queryByRole("list", { name: copy.squad.pitchLabel })).not.toBeInTheDocument();
      expect(screen.queryByText(copy.leagueMembers.starterCount(0))).not.toBeInTheDocument();
      expect(screen.queryByText(copy.leagueMembers.benchCount(0))).not.toBeInTheDocument();
      client.clear();
    },
  );
});
