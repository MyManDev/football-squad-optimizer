import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { RosterEntry } from "../identity/useLeagueIdentity";
import { MemberPicker } from "./MemberPicker";

afterEach(cleanup);

const rows: RosterEntry[] = [
  { entryId: 101, managerName: "Deniz Aral", teamName: "Boğaz FC" },
  { entryId: 202, managerName: "Ece Kaya", teamName: "Kadıköy United" },
];

function draw(onWarm: (entry: RosterEntry) => void, onConfirm = vi.fn()) {
  const members = { status: "success", isPending: false, isError: false, refetch: vi.fn() };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <LanguageProvider>
        <MemoryRouter>
          <MemberPicker
            members={members as never}
            rows={rows}
            onConfirm={onConfirm}
            onWarm={onWarm}
          />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return onConfirm;
}

describe("the member picker's rows", () => {
  it("warm the member a finger lands on before the tap confirms them", () => {
    const warm = vi.fn();
    const confirm = draw(warm);
    const row = screen.getByRole("button", { name: /Ece Kaya/ });

    fireEvent.pointerDown(row);
    expect(warm).toHaveBeenCalledWith(rows[1]);
    expect(confirm).not.toHaveBeenCalled();

    fireEvent.click(row);
    expect(confirm).toHaveBeenCalledWith(rows[1]);
  });

  it("warm the member the focus reaches, as a keyboard moves down the list", () => {
    const warm = vi.fn();
    draw(warm);

    fireEvent.focus(screen.getByRole("button", { name: /Deniz Aral/ }));

    expect(warm).toHaveBeenCalledTimes(1);
    expect(warm).toHaveBeenCalledWith(rows[0]);
  });
});
