import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { AdminPage } from "./AdminPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each(["tr", "en"] as const)(
  "offers admin destinations and an explicit access notice in %s without fetching data",
  (language) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={["/admin"]}>
          <AdminPage />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const copy = MESSAGES[language].admin;

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.title);
    expect(screen.getByText(copy.notice)).toHaveTextContent(
      language === "tr" ? /menüde listelenmez, korumalı değildir/ : /unlisted, not protected/,
    );
    expect(screen.getByRole("link", { name: copy.analysis })).toHaveAttribute("href", "/analysis");
    expect(screen.getByRole("link", { name: copy.status })).toHaveAttribute("href", "/status");
    expect(screen.getByRole("link", { name: copy.decisions })).toHaveAttribute(
      "href",
      "https://github.com/MyManDev/football-squad-optimizer/blob/develop/docs/decisions.md",
    );
    expect(screen.getAllByRole("link")).toHaveLength(3);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(fetch).not.toHaveBeenCalled();
  },
);
