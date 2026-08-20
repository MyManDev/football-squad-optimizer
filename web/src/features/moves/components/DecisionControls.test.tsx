import userEvent from "@testing-library/user-event";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { DecisionControls } from "./DecisionControls";

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

describe("DecisionControls", () => {
  it("defaults to one-week pure points without presenting a rival probability", () => {
    renderControls();

    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Saf Puan/ })).toBeChecked();
    expect(screen.queryByText("diagnostik")).not.toBeInTheDocument();
    expect(screen.getByText("Rakip bütçesi yok")).toBeInTheDocument();
  });

  it("keeps the selected mode and window in the shareable URL", async () => {
    const user = userEvent.setup();
    renderControls();

    await user.click(screen.getByRole("radio", { name: /3 hafta/ }));
    await user.click(screen.getByRole("radio", { name: /Garantici/ }));

    const query = screen.getByLabelText("Current URL query").textContent ?? "";
    expect(new URLSearchParams(query).get("window")).toBe("3");
    expect(new URLSearchParams(query).get("mode")).toBe("garantici");
    expect(screen.getByText("P(geride) 46% → 27%")).toBeInTheDocument();
  });

  it("marks crowd-relative windows as diagnostic rather than probability", () => {
    renderControls("/moves?mode=asiri-agresif&window=5");

    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Aşırı Agresif/ })).toBeChecked();
    expect(screen.getByText("diagnostik")).toBeInTheDocument();
    expect(screen.getByText(/Lig-içi 5 haftalık sonuç bir olasılık değildir/)).toBeInTheDocument();
    expect(screen.getByText(/P\(5\+ önde\) 19%/)).toBeInTheDocument();
  });
});
