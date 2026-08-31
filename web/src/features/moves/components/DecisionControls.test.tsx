import userEvent from "@testing-library/user-event";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { DecisionControls } from "./DecisionControls";

const EVIDENCE = {
  contract_version: "public_horizon_evidence_v1",
  ledger_control_verified: true,
  horizons: [
    {
      horizon: 1,
      decision_role: "live_control",
      solver_status: "OPTIMAL",
      solver_proof_status: "proven",
      publication_status: "decision_eligible",
    },
    {
      horizon: 3,
      decision_role: "research_shadow",
      solver_status: "FEASIBLE",
      solver_proof_status: "unproven",
      publication_status: "shadow_only",
    },
  ],
};

afterEach(cleanup);

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Current URL query">{location.search}</output>;
}

function renderControls(path = "/moves") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DecisionControls />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function renderEntryControls(path = "/league/members/35249001?mode=agresif&window=3") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DecisionControls variant="entry" />
      <LocationProbe />
    </MemoryRouter>,
  );
}

function renderEnglishControls(path = "/moves") {
  return render(
    <LanguageProvider initialLanguage="en">
      <MemoryRouter initialEntries={[path]}>
        <DecisionControls />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("DecisionControls", () => {
  it("defaults to one-week pure points without presenting a rival probability", () => {
    renderControls();

    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Saf Puan/ })).toBeChecked();
    expect(screen.queryByText("diagnostik")).not.toBeInTheDocument();
    expect(screen.getByText("Rakip Bütçesi Yok")).toBeInTheDocument();
    expect(screen.getByText("canlı kontrol")).toBeInTheDocument();
    expect(screen.getByText(/H1 mevcut kararı belirler/)).toBeInTheDocument();
  });

  it("keeps the selected mode and window in the shareable URL", async () => {
    const user = userEvent.setup();
    renderControls();

    await user.click(screen.getByRole("radio", { name: /3 hafta/ }));
    await user.click(screen.getByRole("radio", { name: /Garantici/ }));

    const query = screen.getByLabelText("Current URL query").textContent ?? "";
    expect(new URLSearchParams(query).get("window")).toBe("3");
    expect(new URLSearchParams(query).get("mode")).toBe("garantici");
    expect(screen.getByText("P(geride) %46 → %27")).toBeInTheDocument();
    expect(screen.getByText("araştırma gölgesi")).toBeInTheDocument();
    expect(screen.getByText(/H3 gölge kanıt için ayrılmıştır/)).toBeInTheDocument();
    expect(screen.getByText("araştırma gölgesi").closest('[role="note"]')).toHaveAttribute(
      "aria-live",
      "polite",
    );
  });

  it("explains the horizon role in English as well", () => {
    renderEnglishControls("/moves?window=5");

    expect(screen.getByText("research shadow")).toBeInTheDocument();
    expect(screen.getByText(/H5 is reserved for shadow evidence/)).toBeInTheDocument();
  });

  it("distinguishes computed shadow evidence from an unrun window", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/moves"]}>
        <DecisionControls horizonEvidence={EVIDENCE} />
      </MemoryRouter>,
    );

    expect(screen.getByText(/H1, dondurulmuş ledger kararını aynen üretti/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /3 hafta/ }));
    expect(screen.getByText(/FEASIBLE; çözücü kanıtı: unproven/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /5 hafta/ }));
    expect(screen.getByText(/Sonuç toplu koşudan sonra oluşur/)).toBeInTheDocument();
  });

  it("marks crowd-relative windows as diagnostic rather than probability", () => {
    renderControls("/moves?mode=asiri-agresif&window=5");

    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Aşırı Agresif/ })).toBeChecked();
    expect(screen.getByText("diagnostik")).toBeInTheDocument();
    expect(
      screen.getByText(/Lig-içi 5 haftalık sonuç bir teşhis göstergesidir/),
    ).toBeInTheDocument();
    expect(screen.getByText(/P\(5\+ önde\) %19/)).toBeInTheDocument();
  });

  it("uses point-cost labels without percentages on a member page", () => {
    const { container } = renderEntryControls();

    expect(screen.getByDisplayValue("agresif")).toBeChecked();
    expect(screen.getByText(/~1,8 beklenen puan maliyeti/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("%");
    expect(screen.queryByLabelText("Lig Numarası")).not.toBeInTheDocument();
  });
});
