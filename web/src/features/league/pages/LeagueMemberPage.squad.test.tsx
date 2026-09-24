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

/** The bench under the pitch: a region named for it, one list item per player. */
function benchItems(language: Language = "en"): HTMLElement[] {
  const bench = screen.getByRole("region", { name: MESSAGES[language].leagueMembers.bench });
  return within(bench).getAllByRole("listitem");
}

/** The closed section holding the squad the member holds before the plan's transfers. */
function heldSection(language: Language): HTMLElement {
  const summary = screen.getByText(MESSAGES[language].leagueMembers.memberSquad, {
    selector: "summary span",
  });
  const details = summary.closest("details");
  if (!details) throw new Error("No held squad section");
  return details;
}

describe("the member's published squad", () => {
  it.each(["tr", "en"] as const)(
    "carries no source-record or public-data notice on a partial record in %s",
    (language) => {
      const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
      squad.payload.data_quality = "partial";
      squad.payload.purchase_prices_known = false;
      const raw = ["free_transfers", "purchase_prices", "probability 97% chance"];
      squad.payload.missing_fields = raw;
      const { container } = render(memberSurface(squad, language));

      // The member page is the squad and the plan. The notices left it; the record keeps
      // the fields, and a raw field name never reaches the page.
      expect(
        screen.queryByRole("heading", {
          level: 2,
          name: MESSAGES[language].leagueMembers.publicDataTitle,
        }),
      ).toBeNull();
      for (const field of raw) expect(container).not.toHaveTextContent(field);
      expect(squad.payload.missing_fields).toEqual(raw);
    },
  );
  it.each(["tr", "en"] as const)("shows the entry's XI, captain and bench in %s", (language) => {
    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    const copy = MESSAGES[language];
    render(memberSurface(squad, language));

    // With no plan shown, the pitch draws the squad the member holds.
    expect(
      screen.getByRole("heading", { level: 2, name: copy.leagueMembers.memberSquad }),
    ).toBeInTheDocument();
    const pitch = screen.getByRole("list", { name: copy.squad.pitchLabel });
    expect(
      within(pitch)
        .getAllByRole("listitem")
        .map((row) => row.getAttribute("aria-label")),
    ).toEqual(["GK", "DEF", "MID", "FWD"]);
    for (const player of squad.payload.starting_xi) {
      expect(within(pitch).getByTitle(player.name)).toHaveTextContent(player.short_name);
    }
    expect(pitch.querySelectorAll("[title]")).toHaveLength(11);
    const captain = squad.payload.starting_xi.find((player) => player.is_captain)!;
    const captainChip = within(pitch).getByLabelText(copy.squad.captainLabel).parentElement!;
    expect(within(captainChip).getByTitle(captain.name)).toBeInTheDocument();
    expect(within(pitch).getAllByLabelText(copy.squad.captainLabel)).toHaveLength(1);
    // The held squad names no vice-captain, so none is drawn.
    expect(within(pitch).queryByLabelText(copy.squad.viceCaptainLabel)).toBeNull();
    expect(screen.getByText(copy.leagueMembers.heldViceCaptainUnavailable)).toBeInTheDocument();
    const bench = benchItems(language);
    expect(bench).toHaveLength(4);
    bench.forEach((item, index) =>
      expect(item).toHaveTextContent(squad.payload.bench[index]!.name),
    );
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
    const bench = benchItems();
    expect(bench).toHaveLength(second.payload.bench.length);
    bench.forEach((item, index) =>
      expect(item).toHaveTextContent(second.payload.bench[index]!.name),
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

    const bench = benchItems();
    const expected = [original[0]!, original[2]!, original[3]!, original[1]!];
    bench.forEach((item, index) => expect(item).toHaveTextContent(expected[index]!.name));
    expect(bench.map((item) => item.firstElementChild!.textContent)).toEqual(["1", "3", "4", "—"]);
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

      // The pitch draws the plan, with its vice-captain; the held squad waits, closed.
      const copy = MESSAGES[language];
      const pitch = screen.getByRole("list", { name: copy.squad.pitchLabel });
      const vice = within(pitch).getByLabelText(copy.squad.viceCaptainLabel).parentElement!;
      const viceInEleven = advice.payload.starting_xi!.find(
        (player) => player.player_id === proposedVice.player_id,
      )!;
      expect(within(vice).getByTitle(viceInEleven.name)).toBeInTheDocument();
      const held = heldSection(language);
      expect(held).not.toHaveAttribute("open");
      expect(
        within(held).getByText(copy.leagueMembers.heldViceCaptainUnavailable),
      ).toBeInTheDocument();
      expect(held).not.toHaveTextContent("Proposed Vice Only");
      // It lists the fifteen the member holds, the eleven and the bench.
      expect(within(held).getAllByRole("listitem")).toHaveLength(
        squad.payload.starting_xi.length + squad.payload.bench.length,
      );
      for (const player of [...squad.payload.starting_xi, ...squad.payload.bench]) {
        expect(held).toHaveTextContent(player.name);
      }
      expect(screen.getAllByText("Proposed Vice Only").length).toBeGreaterThan(0);
    },
  );

  it.each(["tr", "en"] as const)("shows absent squad data as unavailable in %s", (language) => {
    const copy = MESSAGES[language];
    render(memberSurface(mockEntrySquadEnvelopes[35249010]!, language));

    expect(screen.getByText(copy.leagueMembers.emptySquad)).toBeInTheDocument();
    expect(screen.getByText(copy.leagueMembers.emptySquadBody)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: copy.squad.pitchLabel })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: copy.leagueMembers.bench })).toBeNull();
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
      expect(screen.queryByRole("region", { name: copy.leagueMembers.bench })).toBeNull();
      client.clear();
    },
  );
});
