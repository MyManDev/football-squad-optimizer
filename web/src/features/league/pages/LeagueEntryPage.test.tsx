import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { LeagueEntryPage } from "./LeagueEntryPage";

const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => localStorage.clear());

function open(language: Language) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<LeagueEntryPage />} />
          <Route path="/league/members" element={<h1>Member destination</h1>} />
        </Routes>
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("league entry in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;
  it("connects through published data without changing the existing viewer selection", async () => {
    const viewer = JSON.stringify({ entryId: 35249001 });
    localStorage.setItem("squadopt.viewer", viewer);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(published)));
    vi.stubGlobal("fetch", fetcher);
    open(language);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByLabelText(copy.label)).toHaveValue("");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), String(published.payload.league_id));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
    expect(localStorage.getItem("squadopt.viewer")).toBe(viewer);
  });

  it("validates decimal IDs before requesting any publication", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    open(language);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(copy.label), "1e3");
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(screen.getByRole("status")).toHaveTextContent(copy.invalid);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each(["unsupported", "missing", "failed"] as const)(
    "states %s without changing routes",
    async (state) => {
      const fetcher = vi
        .fn()
        .mockResolvedValue(
          state === "unsupported"
            ? new Response(JSON.stringify(published))
            : new Response("", { status: state === "missing" ? 404 : 503 }),
        );
      vi.stubGlobal("fetch", fetcher);
      open(language);
      const user = userEvent.setup();
      await user.type(
        screen.getByLabelText(copy.label),
        state === "unsupported" ? "123" : "352490",
      );
      await user.click(screen.getByRole("button", { name: copy.submit }));
      expect(await screen.findByText(copy[state])).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
      if (state === "unsupported") expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it("keeps the submitted ID fixed while its result is pending", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
      ),
    );
    open(language);
    const user = userEvent.setup();
    const field = screen.getByLabelText(copy.label);
    await user.type(field, String(published.payload.league_id));
    await user.click(screen.getByRole("button", { name: copy.submit }));
    expect(field).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.submit })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(copy.loading);
    await act(async () => finish(new Response(JSON.stringify(published))));
    expect(await screen.findByRole("heading", { name: "Member destination" })).toBeInTheDocument();
  });
});
