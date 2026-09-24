import userEvent from "@testing-library/user-event";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "./LanguageProvider";
import { LanguageToggle } from "./LanguageToggle";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.lang = "";
});

describe("LanguageToggle", () => {
  it("names each button by its code, a middle dot and the language", () => {
    render(
      <LanguageProvider initialLanguage="tr">
        <LanguageToggle />
      </LanguageProvider>,
    );

    const group = screen.getByRole("group", { name: "Dil" });
    const turkish = within(group).getByRole("button", { name: "TR · Türkçe" });
    const english = within(group).getByRole("button", { name: "EN · English" });
    // The visible text stays the bare code, so the name starts with what is on screen.
    expect(turkish).toHaveTextContent(/^TR$/);
    expect(english).toHaveTextContent(/^EN$/);
    expect(turkish).toHaveAttribute("aria-pressed", "true");
    expect(english).toHaveAttribute("aria-pressed", "false");
    // No em or en dash in any name.
    for (const button of within(group).getAllByRole("button")) {
      expect(button.getAttribute("aria-label")).not.toMatch(/[–—]/);
    }
  });

  it("switches language from the keyboard and moves the pressed state", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider initialLanguage="tr">
        <LanguageToggle />
      </LanguageProvider>,
    );

    await user.tab();
    expect(screen.getByRole("button", { name: /^TR/ })).toHaveFocus();
    await user.tab();
    const english = screen.getByRole("button", { name: /^EN/ });
    expect(english).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "EN · English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.keyboard(" ");
    expect(screen.getByRole("button", { name: "EN · English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.tab({ shift: true });
    await user.keyboard(" ");
    expect(document.documentElement).toHaveAttribute("lang", "tr");
    expect(screen.getByRole("button", { name: "TR · Türkçe" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
