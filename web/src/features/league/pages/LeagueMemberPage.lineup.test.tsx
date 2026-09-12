/**
 * The published decision is more than the moves: the card shows the armband, the chip,
 * the eleven and the bench order when the producer published them, and nothing invented
 * when it did not.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function renderAdvice(advice: LeagueViewEnvelope<EntryAdvice>, language: "tr" | "en" = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the advice card carries the whole decision", () => {
  it("shows captain, vice-captain, chip, eleven and bench order from the payload", () => {
    const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const payload = advice.payload;
    expect(payload.starting_xi).toHaveLength(11);
    expect(payload.bench).toHaveLength(4);
    renderAdvice(advice);

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

  it("names the chip the plan plays", () => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    renderAdvice({ ...base, payload: { ...base.payload, chip: "3xc" } }, "en");
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
    expect(screen.queryByRole("region", { name: "Bu haftaki kadron" })).toBeNull();
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
    expect(screen.queryByRole("region", { name: "Bu haftaki kadron" })).toBeNull();
  });
});

describe("the published Free Hit squad basis", () => {
  it.each([
    ["tr", "Free Hit oynadın; bu öneri GW 2 kadrona göre."],
    ["en", "Free Hit played; this advice stands on your GW 2 squad."],
  ] as const)("names the prior squad in %s", (language, expected) => {
    const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    renderAdvice(
      { ...base, payload: { ...base.payload, squad_basis: "pre_free_hit_gw02" } },
      language,
    );
    expect(screen.getAllByText(expected)).toHaveLength(1);
  });

  it.each([undefined, "captured", "pre_free_hit_gw2", "pre_free_hit_gw002", "other"])(
    "shows no basis note for %s, including Wildcard and legacy advice",
    (basis) => {
      const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const payload: EntryAdvice = { ...base.payload, chip: "wildcard" };
      if (basis !== undefined) payload.squad_basis = basis;
      renderAdvice({ ...base, payload }, "en");
      expect(screen.queryByText(/Free Hit played;/)).not.toBeInTheDocument();
      expect(screen.getByText("Wildcard")).toBeInTheDocument();
    },
  );
});
