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
  it("renders member standings, the public-data notice and an example badge", () => {
    renderPage(<LeagueMembersView envelope={mockLeagueMembersEnvelope} />);

    expect(screen.getByRole("heading", { level: 1, name: "Lig üyeleri" })).toBeInTheDocument();
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
