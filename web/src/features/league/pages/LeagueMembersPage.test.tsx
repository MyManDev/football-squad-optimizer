import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { LeagueMemberView } from "./LeagueMemberPage";
import { LeagueMembersView } from "./LeagueMembersPage";
import { withLeague } from "../../../testSupport/league";
import { assertMembers } from "../publicationShape";
import { AS_A_CHANCE } from "../../../testSupport/honesty";

afterEach(cleanup);

function renderPage(
  node: React.ReactNode,
  path = "/league/352490/members",
  language: Language = "tr",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[path]}>{withLeague(node)}</MemoryRouter>
    </LanguageProvider>,
  );
}

function membersWith(
  overrides: Partial<import("../types").LeagueMembers>,
): typeof mockLeagueMembersEnvelope {
  return {
    ...mockLeagueMembersEnvelope,
    payload: { ...mockLeagueMembersEnvelope.payload, ...overrides },
  };
}

describe("league member points", () => {
  it.each<Language>(["en", "tr"])(
    "separates unknown, unchanged and counted movement in %s",
    (language) => {
      const original = mockLeagueMembersEnvelope.payload.members.find(
        (member) => member.member_kind === "human",
      )!;
      const states = [
        { movement: "unknown", movement_places: null },
        { movement: "same", movement_places: 0 },
        { movement: "up", movement_places: 2 },
        { movement: "down", movement_places: 3 },
      ] as const;
      const value = membersWith({
        members: states.map((state, index) => ({
          ...original,
          entry_id: 101 + index,
          rank: index + 1,
          manager_name: `Member ${index}`,
          ...state,
        })),
      });
      assertMembers(value);
      const { container } = renderPage(
        <LeagueMembersView envelope={value} />,
        "/league/352490/members",
        language,
      );
      const copy = MESSAGES[language].leagueMembers;
      // Movement is the second column, after the rank: an arrow and the places, '=' for
      // no change, a dash for an unknown previous rank. Each cell's words are its name.
      const cells = [...container.querySelectorAll("tbody tr")].map(
        (row) => row.querySelectorAll("td")[1]!,
      );
      const words = [
        copy.noPreviousRank,
        copy.movementLabel("same", 0),
        copy.movementLabel("up", 2),
        copy.movementLabel("down", 3),
      ];
      expect(cells).toHaveLength(words.length);
      cells.forEach((cell, index) => expect(cell).toHaveAccessibleName(words[index]));
      expect(cells.map((cell) => cell.querySelector('[aria-hidden="true"]')?.textContent)).toEqual([
        "—",
        "=",
        "2",
        "3",
      ]);
      expect(cells[2]!.querySelector("svg path")).not.toBeNull();
      for (const text of [
        copy.noPreviousRank,
        copy.movementLabel("same", 0),
        copy.movementLabel("up", 2),
        copy.movementLabel("down", 3),
      ])
        expect(text).not.toMatch(AS_A_CHANCE);
    },
  );
  it.each([
    { movement: "up", movement_places: null },
    { movement: "up", movement_places: 0 },
    { movement: "same", movement_places: null },
    { movement: "same", movement_places: 0, rank: 0 },
    { movement: "same", movement_places: 0, rank: -1 },
    { movement: "same", movement_places: 0, rank: 1.5 },
    { movement: "unknown", movement_places: null, rank: -1 },
    { movement: "unknown", movement_places: 1 },
    { movement: "down", movement_places: -1 },
    { movement: "down", movement_places: 1.5 },
  ] as const)("rejects inconsistent movement at the publication boundary: %s", (state) => {
    const value = structuredClone(mockLeagueMembersEnvelope);
    Object.assign(value.payload.members[0], state);
    expect(() => assertMembers(value)).toThrow();
  });
  it("names the week the points belong to, because the view is labelled with another", () => {
    // The members view carries the *upcoming* gameweek; the scores are last week's. A
    // column headed only "GW points" would sit under the wrong number.
    renderPage(<LeagueMembersView envelope={membersWith({ scored_gameweek: 1 })} />);

    expect(screen.getByRole("columnheader", { name: "OH1 net puanı" })).toBeInTheDocument();
  });

  it("nets every row's week by that row's own transfer hit", () => {
    // The defect this pins: our row was net of our hit and each member's was gross of
    // theirs, in one column. A member who took a four-point hit read four points better
    // than they scored — the source's own total advances by points minus the hit.
    const hit = membersWith({
      scored_gameweek: 3,
      members: [
        {
          ...mockLeagueMembersEnvelope.payload.members[0],
          gameweek_points: 78,
          transfer_cost: 4,
        },
        {
          ...mockLeagueMembersEnvelope.payload.members[1],
          gameweek_points: 51,
          transfer_cost: 0,
        },
      ],
    });
    renderPage(<LeagueMembersView envelope={hit} />);

    const cells = screen.getAllByRole("row").slice(1);
    expect(cells[0].textContent).toContain("74");
    expect(cells[0].textContent).not.toContain("78");
    expect(cells[1].textContent).toContain("51");
  });

  it("shows no week at all when the hit that week is unproven", () => {
    // An absent hit is not a hit of zero. Publishing the gross score under a heading
    // that says net would be the same wrong claim on a different row.
    const unknownHit = membersWith({
      scored_gameweek: 3,
      members: [
        {
          ...mockLeagueMembersEnvelope.payload.members[0],
          gameweek_points: 78,
          transfer_cost: null,
        },
      ],
    });
    renderPage(<LeagueMembersView envelope={unknownHit} />);

    const cells = screen.getAllByRole("row").slice(1);
    expect(cells[0].textContent).not.toContain("78");
    expect(cells[0].textContent).toContain("—");
  });

  it("says why the column is empty rather than leaving it blank", () => {
    // A column of dashes with no explanation reads as "everyone scored nothing".
    const noWeek = membersWith({
      scored_gameweek: null,
      members: mockLeagueMembersEnvelope.payload.members.map((member) => ({
        ...member,
        gameweek_points: null,
        total_points: null,
      })),
    });
    renderPage(<LeagueMembersView envelope={noWeek} />);

    expect(screen.getByText(/Henüz kesinleşmiş oyun haftası yok/)).toBeInTheDocument();
  });

  it("shows a measured zero as zero, and an unproven score as a dash", () => {
    // The distinction the whole column rests on: a member can honestly score nothing, and
    // that is not the same statement as "the capture does not prove their score".
    const mixed = membersWith({
      scored_gameweek: 1,
      members: [
        { ...mockLeagueMembersEnvelope.payload.members[0], gameweek_points: 0, total_points: 0 },
        {
          ...mockLeagueMembersEnvelope.payload.members[1],
          gameweek_points: null,
          total_points: null,
        },
      ],
    });
    renderPage(<LeagueMembersView envelope={mixed} />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("0");
    expect(rows[1].textContent).toContain("—");
  });
});

/** The system squad's score explanation, which no member surface carries. */
const SYSTEM_SCORE_NOTE = /recorded squad net|kaydedilen kadro neti/i;

describe("league member surfaces", () => {
  it.each(["tr", "en"] as const)(
    "keeps member surfaces free of the system squad and its comparisons in %s",
    (language) => {
      const copy = MESSAGES[language];
      renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />, undefined, language);
      expect(screen.queryByText(SYSTEM_SCORE_NOTE)).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "SquadOpt" })).not.toBeInTheDocument();
      // No row, badge or link of the system's own team: the table lists the members only.
      expect(document.querySelector("#league-member-list tbody")).not.toHaveTextContent("SquadOpt");
      expect(screen.queryByRole("link", { name: /SquadOpt/ })).not.toBeInTheDocument();
      expect(document.querySelector('a[href$="/squadopt"]')).toBeNull();
      expect(copy.leagueMembers).not.toHaveProperty("systemTeamBadge");
      cleanup();
      const entryId = 35249001;
      renderPage(
        <LeagueMemberView
          index={mockEntryAdviceIndex(entryId).payload}
          squad={mockEntrySquadEnvelopes[entryId]!}
          advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
        />,
        `/league/352490/members/${entryId}`,
        language,
      );
      expect(screen.queryByText(SYSTEM_SCORE_NOTE)).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", {
          name: /Recorded score difference|Kaydedilen puan farkı/,
        }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/point difference from SquadOpt|puan farkın/)).toBeNull();
      expect(mockEntrySquadEnvelopes[entryId]!.payload.squadopt_comparison).not.toBeNull();
    },
  );

  it("omits the system score explanation when no system row is shown", () => {
    renderPage(
      <LeagueMembersView
        envelope={membersWith({
          members: mockLeagueMembersEnvelope.payload.members.filter(
            (member) => member.member_kind !== "system",
          ),
        })}
      />,
    );
    expect(screen.queryByText(SYSTEM_SCORE_NOTE)).not.toBeInTheDocument();
  });

  it("lists only the published human members when the live envelope has no system row", () => {
    const live = {
      ...mockLeagueMembersEnvelope,
      payload: {
        ...mockLeagueMembersEnvelope.payload,
        members: mockLeagueMembersEnvelope.payload.members.filter(
          (member) => member.member_kind !== "system",
        ),
      },
    };
    renderPage(<LeagueMembersView envelope={live} />);

    expect(screen.getAllByRole("row")).toHaveLength(live.payload.members.length + 1);
    expect(screen.queryByRole("link", { name: "SquadOpt" })).not.toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "titles the page with the league's name alone, with no count or gameweek line, in %s",
    (language) => {
      renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />, undefined, language);
      const view = mockLeagueMembersEnvelope.payload;
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(view.league_name);
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      const text = document.body.textContent ?? "";
      expect(text).not.toMatch(/hafta sonunda|after gameweek/);
      expect(text).not.toMatch(/\b\d+ (üye|members)\b/);
      expect(text).not.toMatch(/Hangisi sensin\?|Which one is you\?/);
      expect(text).not.toMatch(/Bu benim|This is me/);
    },
  );

  it("excludes a published virtual system row from both the visitor list and its count", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    const humans = mockLeagueMembersEnvelope.payload.members.filter(
      (member) => member.member_kind === "human",
    );
    expect(screen.getAllByRole("row")).toHaveLength(humans.length + 1);
    expect(screen.queryByText(/SquadOpt · /)).not.toBeInTheDocument();
  });

  it("renders member standings and an example badge, and no notice under the table", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    expect(
      screen.getByRole("heading", { level: 1, name: "SquadOpt Classic League" }),
    ).toBeInTheDocument();
    expect(screen.getByText("örnek veri")).toBeInTheDocument();
    expect(screen.queryByText(/herkese açık FPL verisidir/)).toBeNull();
    expect(screen.queryByText("Tablo hakkında")).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.getByRole("link", { name: "Deniz Aral" })).toHaveAttribute(
      "href",
      "/league/352490/members/35249001",
    );
    expect(screen.queryByRole("link", { name: "SquadOpt" })).not.toBeInTheDocument();
  });

  it("shows point-cost labels and no probability percentage on member advice", () => {
    const entryId = 35249001;
    const advice = mockEntryAdviceEnvelope(entryId, "ortak-koru", 1);
    const { container } = renderPage(
      <LeagueMemberView
        index={mockEntryAdviceIndex(entryId).payload}
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={advice}
      />,
      `/league/352490/members/${entryId}?mode=ortak-koru&window=1`,
    );

    expect(screen.getAllByText("örnek veri").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("ortak-koru")).toBeChecked();
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getAllByText(/beklenen puan maliyeti/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Önerin senin kadrondan/)).toBeInTheDocument();
    // The member page carries the squad and the plan; the public-data notices left it.
    expect(screen.queryByText(/Satın alma fiyatları/)).toBeNull();
    expect(screen.queryByText(/herkese açık FPL verisidir/)).toBeNull();
    expect(container.textContent).not.toContain("%");
    cleanup();

    // The free transfers are on the chips page of their own.
    const chips = renderPage(
      <LeagueMemberView
        index={mockEntryAdviceIndex(entryId).payload}
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={advice}
        tool="chips"
      />,
      `/league/352490/members/${entryId}/chips?mode=ortak-koru&window=1`,
    );
    const transferCard = screen
      .getByRole("heading", { name: "Ücretsiz transfer hakkı" })
      .closest("section");
    expect(transferCard).toHaveTextContent("Bilinmiyor");
    expect(transferCard).not.toHaveTextContent("banka edilmiş ikinci transfer");
    expect(chips.container.textContent).not.toContain("%");
  });

  it("prices the competitive plan against a real rival, and saf-puan carries no price line", () => {
    const entryId = 35249001;
    renderPage(
      <LeagueMemberView
        index={mockEntryAdviceIndex(entryId).payload}
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "ortak-koru", 1)}
      />,
      `/league/352490/members/${entryId}?mode=ortak-koru`,
    );
    expect(screen.getByText(/beklenen puandan vazgeçiyor/)).toBeInTheDocument();
    expect(screen.getByText(/kadrosuna göre fiyatlandı/)).toBeInTheDocument();

    cleanup();
    renderPage(
      <LeagueMemberView
        index={mockEntryAdviceIndex(entryId).payload}
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
      />,
      `/league/352490/members/${entryId}`,
    );
    expect(screen.queryByText(/beklenen puandan vazgeçiyor/)).not.toBeInTheDocument();
  });

  it("renders the empty-squad branch without presenting advice", () => {
    const entryId = 35249010;
    renderPage(
      <LeagueMemberView
        index={mockEntryAdviceIndex(entryId).payload}
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
      />,
      `/league/352490/members/${entryId}`,
    );

    expect(screen.getByText("Bu üye için kadro bulunmuyor.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Bu kayıt, transfersiz bir öneri olduğunu doğrulayacak kadar plan bilgisi içermiyor.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Pozisyona göre ilk on bir" }),
    ).not.toBeInTheDocument();
  });
});

describe.each(["tr", "en"] as const)("published overlap bounds in %s", (language) => {
  it.each([
    ["within_free_transfers", "OPTIMAL"],
    ["within_free_transfers", "FEASIBLE"],
    ["with_hits", "OPTIMAL"],
    ["with_hits", "FEASIBLE"],
  ] as const)("keeps %s / %s bounds separate from the measured player count", (kind, solver) => {
    // Published GW4 member 313686 vs 5662073: the recommended 15 share four IDs
    // with the rival XI, while fark-yarat's applied maximum remains five.
    const recommendedIds = [
      154561, 466075, 522047, 106760, 141746, 446008, 466052, 424876, 219168, 475168, 177815,
      489639, 60307, 487676, 472769,
    ];
    const rivalXiIds = new Set([
      116535, 106760, 606702, 465730, 441302, 141746, 176297, 466052, 209244, 219168, 223094,
    ]);
    const measuredOverlap = recommendedIds.filter((id) => rivalXiIds.has(id)).length;
    expect(new Set(recommendedIds).size).toBe(15);
    expect(rivalXiIds.size).toBe(11);
    expect(measuredOverlap).toBe(4);
    const entryId = 35249001;
    const index = mockEntryAdviceIndex(entryId).payload;
    const rivalId = index.default_rival_entry_id!;
    const advice = mockEntryAdviceEnvelope(entryId, "fark-yarat", 1, rivalId);
    advice.payload.overlap_count = measuredOverlap;
    advice.payload.overlap_target = 5;
    advice.payload.overlap_applied = 5;
    advice.payload.transfer_cap = 1;
    advice.payload.transfer_hit_points = 0;
    advice.payload.expected_points_cost = 0;
    advice.payload.expected_points_cost_ceiling = 0;
    advice.payload.solver_status = solver;
    advice.payload.plan_kind = kind;
    advice.payload.alternative_plan = {
      kind: kind === "with_hits" ? "within_free_transfers" : "with_hits",
      overlap_applied: 5,
      transfer_hit_points: 0,
      expected_points_cost: 0,
      expected_points_cost_ceiling: 0,
    };
    renderPage(
      <LeagueMemberView squad={mockEntrySquadEnvelopes[entryId]!} advice={advice} index={index} />,
      `/league/352490/members/${entryId}?mode=fark-yarat&rival=${rivalId}`,
      language,
    );
    const copy = MESSAGES[language].leagueMembers;
    expect(screen.getByText((text) => text.includes(copy.overlapLine(4)))).toBeInTheDocument();
    expect(
      screen.queryByText((text) => text.includes(copy.overlapLine(5))),
    ).not.toBeInTheDocument();
    const paragraph = screen.getByText(
      language === "tr" ? /istenen ortak oyuncu sınırı 5/ : /requested overlap bound 5/,
    );
    expect(paragraph).toHaveTextContent(
      language === "tr" ? "uygulanan ortak oyuncu sınırı 5" : "applied overlap bound 5",
    );
    expect(paragraph).not.toHaveTextContent(
      /reached|reachable|ulaş|still came out ahead|önde çıktı/i,
    );
    if (kind === "within_free_transfers")
      expect(paragraph).toHaveTextContent(
        language === "tr" ? "transfer cezası 0 puan" : "transfer penalties 0 points",
      );
    // The hits are the plan's own, whether a publish or the member's device solved it.
    expect(paragraph).not.toHaveTextContent(/published|yayımlanan/i);
    if (solver === "FEASIBLE")
      expect(paragraph).toHaveTextContent(language === "tr" ? "maliyet en fazla" : "cost at most");
  });
});
