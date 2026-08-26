import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LeagueMemberView } from "./LeagueMemberPage";
import { LeagueMembersView } from "./LeagueMembersPage";

afterEach(cleanup);

function renderPage(node: React.ReactNode, path = "/league/members") {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </LanguageProvider>,
  );
}

describe("league member surfaces", () => {
  it("appends our own row when the live envelope has none, and claims no rank for it", () => {
    const live = {
      ...mockLeagueMembersEnvelope,
      payload: {
        ...mockLeagueMembersEnvelope.payload,
        members: mockLeagueMembersEnvelope.payload.members.filter(
          (member) => member.member_kind !== "system",
        ),
      },
    };
    renderPage(
      <LeagueMembersView
        envelope={live}
        systemRow={{
          member_kind: "system",
          entry_id: null,
          manager_name: "SquadOpt",
          team_name: "SquadOpt",
          rank: 0,
          gameweek_points: 26,
          total_points: 26,
          movement: "unknown",
          movement_places: null,
          data_quality: "complete",
        }}
      />,
    );

    expect(screen.getByText("SquadOpt · sistem takımı")).toBeInTheDocument();
    // Placing ourselves among the members needs their points, which the standings view
    // does not carry; an invented rank would be the page's one unmeasured number.
    const systemCells = screen.getByRole("link", { name: "SquadOpt" }).closest("tr")!;
    expect(systemCells.querySelector("td")!.textContent).toBe("—");
  });

  it("does not double our row when the envelope already carries one", () => {
    renderPage(
      <LeagueMembersView
        envelope={mockLeagueMembersEnvelope}
        systemRow={{
          member_kind: "system",
          entry_id: null,
          manager_name: "SquadOpt",
          team_name: "SquadOpt",
          rank: 0,
          gameweek_points: 26,
          total_points: 26,
          movement: "unknown",
          movement_places: null,
          data_quality: "complete",
        }}
      />,
    );

    expect(screen.getAllByText("SquadOpt · sistem takımı")).toHaveLength(1);
  });

  it("renders member standings, the public-data notice and an example badge", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    expect(screen.getByRole("heading", { level: 1, name: "Lig Üyeleri" })).toBeInTheDocument();
    expect(screen.getByText("örnek veri")).toBeInTheDocument();
    expect(screen.getByText(/son tarihinden sonra herkese açık FPL verisidir/)).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(12);
    expect(screen.getByRole("link", { name: "Deniz Aral" })).toHaveAttribute(
      "href",
      "/league/members/35249001",
    );
    expect(screen.getByText("SquadOpt · sistem takımı")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SquadOpt" })).toHaveAttribute(
      "href",
      "/league/members/squadopt",
    );
  });

  it("shows point-cost labels and no probability percentage on member advice", () => {
    const entryId = 35249001;
    const advice = mockEntryAdviceEnvelope(entryId, "agresif", 3);
    const { container } = renderPage(
      <LeagueMemberView squad={mockEntrySquadEnvelopes[entryId]!} advice={advice} />,
      `/league/members/${entryId}?mode=agresif&window=3`,
    );

    expect(screen.getAllByText("örnek veri").length).toBeGreaterThan(0);
    expect(screen.getByDisplayValue("agresif")).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeChecked();
    expect(screen.getAllByText(/beklenen puan maliyeti/).length).toBeGreaterThan(0);
    expect(screen.getByText(/yalnızca senin kadrondan/)).toBeInTheDocument();
    expect(screen.getByText(/banka edilmiş ikinci transfer/)).toBeInTheDocument();
    expect(screen.getByText(/Satın alma fiyatları public değildir/)).toBeInTheDocument();
    expect(screen.getByText(/puan farkın: \+9/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
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
