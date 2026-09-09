import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { LeagueMemberView } from "./LeagueMemberPage";
import { LeagueMembersView } from "./LeagueMembersPage";

afterEach(cleanup);

function renderPage(node: React.ReactNode, path = "/league/members", language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
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

describe("league member surfaces", () => {
  it.each(["tr", "en"] as const)(
    "keeps member surfaces free of the system squad and its comparisons in %s",
    (language) => {
      const copy = MESSAGES[language];
      renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />, undefined, language);
      expect(screen.queryByText(copy.league.note)).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "SquadOpt" })).not.toBeInTheDocument();
      expect(screen.queryByText(copy.leagueMembers.systemTeamBadge)).not.toBeInTheDocument();
      cleanup();
      const entryId = 35249001;
      renderPage(
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[entryId]!}
          advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
        />,
        `/league/members/${entryId}`,
        language,
      );
      expect(screen.queryByText(copy.league.note)).not.toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: copy.leagueMembers.squadoptComparisonTitle }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(copy.leagueMembers.squadoptComparison("+9")),
      ).not.toBeInTheDocument();
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
    expect(screen.queryByText(MESSAGES.tr.league.note)).not.toBeInTheDocument();
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
    expect(
      screen.getByText(MESSAGES.tr.leagueMembers.memberCount(live.payload.members.length)),
    ).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "names the column's basis, because it is not the one the FPL site shows, in %s",
    (language) => {
      const copy = MESSAGES[language];
      renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />, undefined, language);

      expect(screen.getByText(copy.leagueMembers.gameweekNetNote)).toBeInTheDocument();
    },
  );

  it("keeps the basis note when no row of ours is in the column", () => {
    // The basis belongs to the column, not to our presence in it: a member reading only
    // other members still sees numbers that differ from the ones on the FPL site.
    renderPage(
      <LeagueMembersView
        envelope={membersWith({
          members: mockLeagueMembersEnvelope.payload.members.filter(
            (member) => member.member_kind !== "system",
          ),
        })}
      />,
    );
    expect(screen.getByText(MESSAGES.tr.leagueMembers.gameweekNetNote)).toBeInTheDocument();
  });

  it("excludes a published virtual system row from both the visitor list and its count", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    const humans = mockLeagueMembersEnvelope.payload.members.filter(
      (member) => member.member_kind === "human",
    );
    expect(screen.getAllByRole("row")).toHaveLength(humans.length + 1);
    expect(
      screen.getByText(MESSAGES.tr.leagueMembers.memberCount(humans.length)),
    ).toBeInTheDocument();
    expect(screen.queryByText("SquadOpt · sistem takımı")).not.toBeInTheDocument();
  });

  it("renders member standings, the public-data notice and an example badge", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    expect(screen.getByRole("heading", { level: 1, name: "Lig Üyeleri" })).toBeInTheDocument();
    expect(screen.getByText("örnek veri")).toBeInTheDocument();
    expect(screen.getByText(/son tarihinden sonra herkese açık FPL verisidir/)).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.getByRole("link", { name: "Deniz Aral" })).toHaveAttribute(
      "href",
      "/league/members/35249001",
    );
    expect(screen.queryByRole("link", { name: "SquadOpt" })).not.toBeInTheDocument();
  });

  it("shows point-cost labels and no probability percentage on member advice", () => {
    const entryId = 35249001;
    const advice = mockEntryAdviceEnvelope(entryId, "ortak-koru", 1);
    const { container } = renderPage(
      <LeagueMemberView squad={mockEntrySquadEnvelopes[entryId]!} advice={advice} />,
      `/league/members/${entryId}?mode=ortak-koru&window=1`,
    );

    expect(screen.getAllByText("örnek veri").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("ortak-koru")).toBeChecked();
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getAllByText(/beklenen puan maliyeti/).length).toBeGreaterThan(0);
    expect(screen.getByText(/yalnızca senin kadrondan/)).toBeInTheDocument();
    expect(screen.getByText(/banka edilmiş ikinci transfer/)).toBeInTheDocument();
    expect(screen.getByText(/Satın alma fiyatları public değildir/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
  });

  it("prices the competitive plan against a real rival, and saf-puan carries no price line", () => {
    const entryId = 35249001;
    renderPage(
      <LeagueMemberView
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "garantici", 1)}
      />,
      `/league/members/${entryId}?mode=garantici`,
    );
    expect(screen.getByText(/beklenen puandan vazgeçiyor/)).toBeInTheDocument();
    expect(screen.getByText(/Harbor Rovers kadrosuna göre fiyatlandı/)).toBeInTheDocument();

    cleanup();
    renderPage(
      <LeagueMemberView
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
      />,
      `/league/members/${entryId}`,
    );
    expect(screen.queryByText(/beklenen puandan vazgeçiyor/)).not.toBeInTheDocument();
  });

  it("renders the empty-squad branch without presenting advice", () => {
    const entryId = 35249010;
    renderPage(
      <LeagueMemberView
        squad={mockEntrySquadEnvelopes[entryId]!}
        advice={mockEntryAdviceEnvelope(entryId, "saf-puan", 1)}
      />,
      `/league/members/${entryId}`,
    );

    expect(screen.getByText("Bu üye için kadro bulunmuyor.")).toBeInTheDocument();
    expect(
      screen.getByText("Kaynak kadro eksik olduğu için öneri gösterilmiyor."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Pozisyona göre ilk on bir" }),
    ).not.toBeInTheDocument();
  });
});
