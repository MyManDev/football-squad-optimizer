/**
 * The published decision is more than the moves: the card shows the armband, the chip,
 * the eleven and the bench order when the producer published them, and nothing invented
 * when it did not. The pitch draws that week; its list view ('Liste') reads it out.
 */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function renderAdvice(
  advice: LeagueViewEnvelope<EntryAdvice>,
  language: "tr" | "en" = "tr",
  squad: LeagueViewEnvelope<EntrySquad> = mockEntrySquadEnvelopes[ENTRY]!,
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={squad}
          advice={advice}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

/** Switches the squad section from the pitch to its list, where the lineup is read out. */
function openList(language: "tr" | "en" = "tr") {
  const list = screen.getByRole("button", { name: MESSAGES[language].leagueMembers.viewList });
  fireEvent.click(list);
  expect(list).toHaveAttribute("aria-pressed", "true");
}

describe("the advice card carries the whole decision", () => {
  it("shows captain, vice-captain, chip, eleven and bench order from the payload", () => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const payload = advice.payload;
    expect(payload.starting_xi).toHaveLength(11);
    expect(payload.bench).toHaveLength(4);
    renderAdvice(advice);
    // The pitch is shown first; the list waits behind the toggle.
    expect(screen.queryByRole("region", { name: "Bu haftaki kadron" })).toBeNull();
    openList();

    const lineup = screen.getByRole("region", { name: "Bu haftaki kadron" });
    expect(within(lineup).getByText("Kaptan")).toBeInTheDocument();
    expect(within(lineup).getByText("Yedek kaptan")).toBeInTheDocument();
    expect(within(lineup).getByText("Bu hafta çip yok")).toBeInTheDocument();
    expect(within(lineup).getAllByText(payload.captain!.name).length).toBeGreaterThan(0);
    expect(within(lineup).getAllByText(payload.vice_captain!.name).length).toBeGreaterThan(0);
    // The bench is listed in the producer's order, goalkeeper first.
    expect(payload.bench![0]!.position).toBe("GK");
    const rows = within(lineup).getAllByText(/xP$/);
    expect(rows).toHaveLength(15);
  });

  it("reads the week out one row a player, with the pitch's marks and a bar per figure", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const payload = base.payload;
    const eleven = payload.starting_xi!;
    // One starter with no published figure: no bar, no figure, never a 0.
    const silent = eleven[1]!;
    const withSilent: EntryAdvice = {
      ...payload,
      starting_xi: eleven.map((player) => {
        if (player.player_id !== silent.player_id) return player;
        const { expected_points: _unstated, ...rest } = player;
        return rest;
      }),
    };
    renderAdvice({ ...base, payload: withSilent });
    openList();
    const lineup = screen.getByRole("region", { name: "Bu haftaki kadron" });
    const [first, second] = within(lineup).getAllByRole("list");
    const starters = within(first!).getAllByRole("listitem");
    const bench = within(second!).getAllByRole("listitem");
    expect(starters).toHaveLength(11);
    expect(bench).toHaveLength(4);
    const codes = MESSAGES.tr.positionCodes;
    // The eleven lead with the position code, the bench with its published place.
    starters.forEach((row, index) =>
      expect(row.firstElementChild).toHaveTextContent(
        codes[eleven[index]!.position as keyof typeof codes],
      ),
    );
    expect(bench.map((row) => row.firstElementChild!.textContent)).toEqual(["1", "2", "3", "4"]);
    // The bench adds the position word after the club, as the held list does.
    expect(bench[0]).toHaveTextContent(MESSAGES.tr.positions.GK);
    // The captain and vice-captain carry the pitch's marks, each on one row only.
    const captain = within(lineup).getAllByRole("img", { name: MESSAGES.tr.squad.captainLabel });
    expect(captain).toHaveLength(1);
    expect(captain[0]!.closest("li")).toHaveTextContent(payload.captain!.name);
    const vice = within(lineup).getAllByRole("img", { name: MESSAGES.tr.squad.viceCaptainLabel });
    expect(vice).toHaveLength(1);
    expect(vice[0]!.closest("li")).toHaveTextContent(payload.vice_captain!.name);
    // Every player a move brings in is marked new, and nobody else.
    const incoming = new Set(payload.moves.map((move) => move.player_in?.name));
    for (const row of starters) {
      const name = eleven.find((player) => row.textContent!.includes(player.name))!.name;
      expect(within(row).queryByText(MESSAGES.tr.leagueMembers.boardNew) !== null).toBe(
        incoming.has(name),
      );
    }
    // The starter with no figure has neither a bar nor a number; the others have both.
    const silentRow = starters.find((row) => row.textContent!.includes(silent.name))!;
    expect(silentRow.textContent).not.toMatch(/xP/);
    expect(silentRow.querySelector("[style]")).toBeNull();
    expect(within(lineup).getAllByText(/xP$/)).toHaveLength(14);
    const bars = lineup.querySelectorAll<HTMLElement>("li [style]");
    expect(bars).toHaveLength(14);
    // One scale for the whole list: at least eight points, and at least the biggest figure.
    const scale = Number(lineup.style.getPropertyValue("--scale"));
    const figures = [...withSilent.starting_xi!, ...payload.bench!]
      .map((player) => player.expected_points)
      .filter((value): value is number => typeof value === "number");
    expect(scale).toBeGreaterThanOrEqual(Math.max(8, ...figures));
  });

  it("names the chip the plan plays", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    renderAdvice({ ...base, payload: { ...base.payload, chip: "3xc" } }, "en");
    openList("en");
    const lineup = screen.getByRole("region", { name: "Your gameweek" });
    expect(within(lineup).getByText("Triple Captain")).toBeInTheDocument();
  });

  it("shows no lineup for a decision published without one", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const stripped: EntryAdvice = {
      ...base.payload,
      expected_own_points: null,
      captain: null,
      vice_captain: null,
      starting_xi: null,
      bench: null,
      chip: null,
    };
    renderAdvice({ ...base, payload: stripped });
    expect(screen.queryByRole("region", { name: "Bu haftaki kadron", hidden: true })).toBeNull();
    // With no published eleven there is no list to switch to.
    expect(screen.queryByRole("button", { name: "Liste" })).toBeNull();
  });

  it("shows no lineup for a legacy document that never carried the fields", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const {
      expected_own_points: _own,
      captain: _captain,
      vice_captain: _vice,
      starting_xi: _eleven,
      bench: _bench,
      chip: _chip,
      ...legacy
    } = base.payload;
    renderAdvice({ ...base, payload: legacy as EntryAdvice });
    expect(screen.queryByRole("region", { name: "Bu haftaki kadron", hidden: true })).toBeNull();
    expect(screen.queryByRole("button", { name: "Liste" })).toBeNull();
  });
});

describe("the published Free Hit squad basis", () => {
  it.each([
    ["tr", "Free Hit oynadın; bu öneri GW 2 kadrona göre."],
    ["en", "Free Hit played; this advice stands on your GW 2 squad."],
  ] as const)("names the prior squad in %s", (language, expected) => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    squad.payload.squad_basis = "pre_free_hit_gw02";
    squad.payload.active_chip = "freehit";
    renderAdvice(
      { ...base, payload: { ...base.payload, squad_basis: "pre_free_hit_gw02" } },
      language,
      squad,
    );
    expect(screen.getAllByText(expected)).toHaveLength(1);
  });

  it("names the prior squad when the advice document carries no basis of its own", () => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    squad.payload.squad_basis = "pre_free_hit_gw02";
    const payload = { ...advice.payload };
    delete payload.squad_basis;
    renderAdvice({ ...advice, payload }, "en", squad);
    expect(
      screen.getByText("Free Hit played; this advice stands on your GW 2 squad."),
    ).toBeInTheDocument();
  });
});

/**
 * The two documents disagreeing is not the same fact as neither of them saying anything,
 * and the card is not allowed to render them the same way. A member whose squad really is
 * a pre-Free-Hit squad would otherwise read a blank card as "nothing to report", which is
 * the silence the rotation evidence contract keeps its own column to avoid asserting.
 */
describe("a squad basis the two documents disagree about", () => {
  const UNCONFIRMED = {
    en: "The squad this advice stands on could not be confirmed: the squad document and the advice document name different ones. Neither week is shown, because a wrong week is worse than no week. Check the fifteen on this page against your own team before using these moves.",
    tr: "Bu önerinin dayandığı kadro doğrulanamadı: kadro belgesi ile öneri belgesi farklı kadro gösteriyor. Hiçbir hafta yazılmıyor, çünkü yanlış bir hafta yazmak hiç yazmamaktan kötü. Bu hamleleri kullanmadan önce bu sayfadaki on beş oyuncuyu kendi takımınla karşılaştır.",
  } as const;

  it.each(["en", "tr"] as const)("says so, and names neither week, in %s", (language) => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
    squad.payload.squad_basis = "pre_free_hit_gw02";
    renderAdvice(
      { ...advice, payload: { ...advice.payload, squad_basis: "pre_free_hit_gw03" } },
      language,
      squad,
    );
    // Neither week, and no other number that could be read as one: the sentence has no digit.
    expect(screen.getByText(UNCONFIRMED[language]).textContent).not.toMatch(/\d/);
    expect(screen.queryByText(/Free Hit played;|Free Hit oynadın;/)).not.toBeInTheDocument();
  });

  it.each(["captured", "pre_free_hit_gw2", "pre_free_hit_gw002", "other"])(
    "is still a disagreement when the entry basis is %s rather than a week",
    (basis) => {
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const payload: EntryAdvice = { ...base.payload, squad_basis: "pre_free_hit_gw02" };
      const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
      squad.payload.squad_basis = basis;
      renderAdvice({ ...base, payload }, "en", squad);
      expect(screen.getByText(UNCONFIRMED.en)).toBeInTheDocument();
      expect(screen.queryByText(/Free Hit played;/)).not.toBeInTheDocument();
    },
  );

  it.each(["en", "tr"] as const)(
    "says nothing at all when the entry carries no basis, in %s",
    (language) => {
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const payload: EntryAdvice = {
        ...base.payload,
        chip: "wildcard",
        squad_basis: "pre_free_hit_gw02",
      };
      const squad = structuredClone(mockEntrySquadEnvelopes[ENTRY]!);
      delete squad.payload.squad_basis;
      squad.payload.active_chip = "wildcard";
      renderAdvice({ ...base, payload }, language, squad);
      expect(screen.queryByText(UNCONFIRMED[language])).not.toBeInTheDocument();
      expect(screen.queryByText(/Free Hit played;|Free Hit oynadın;/)).not.toBeInTheDocument();
      openList(language);
      const lineup = language === "en" ? "Your gameweek" : "Bu haftaki kadron";
      expect(
        within(screen.getByRole("region", { name: lineup })).getByText("Wildcard"),
      ).toBeInTheDocument();
    },
  );
});
