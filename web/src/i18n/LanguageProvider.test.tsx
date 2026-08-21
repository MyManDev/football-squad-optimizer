import userEvent from "@testing-library/user-event";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useLanguage } from "./context";
import { LanguageProvider, LANGUAGE_STORAGE_KEY } from "./LanguageProvider";
import { LanguageToggle } from "./LanguageToggle";

function Probe() {
  const { language, messages } = useLanguage();
  return (
    <output aria-label="active language">
      {language}:{messages.shell.moves}
    </output>
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.lang = "";
});

describe("LanguageProvider", () => {
  it("defaults to Turkish and records the document language", () => {
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    );

    expect(screen.getByLabelText("active language")).toHaveTextContent("tr:Önerilen hamleler");
    expect(document.documentElement).toHaveAttribute("lang", "tr");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("tr");
  });

  it("switches to English and restores the saved preference", async () => {
    const user = userEvent.setup();
    const first = render(
      <LanguageProvider>
        <LanguageToggle />
        <Probe />
      </LanguageProvider>,
    );

    await user.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByLabelText("active language")).toHaveTextContent("en:Suggested moves");
    expect(document.documentElement).toHaveAttribute("lang", "en");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");

    first.unmount();
    render(
      <LanguageProvider>
        <Probe />
      </LanguageProvider>,
    );
    expect(screen.getByLabelText("active language")).toHaveTextContent("en:Suggested moves");
  });
});
