import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { Language } from "../../i18n/messages";
import { PRIVACY_COPY } from "./privacyCopy";
import { PrivacyPage } from "./PrivacyPage";

afterEach(cleanup);

function mount(language: Language) {
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter>
        <PrivacyPage />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the privacy page", () => {
  it.each(["tr", "en"] as const)("names every flow in %s, Google Gemini among them", (language) => {
    mount(language);
    const copy = PRIVACY_COPY[language];
    expect(screen.getByRole("heading", { level: 1, name: copy.title })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(copy.sections.length);
    const llmopt = screen.getByRole("heading", { level: 2, name: "LLMOPT" }).parentElement!;
    expect(within(llmopt).getByText(/Google Gemini/)).toBeInTheDocument();
  });

  it.each([
    ["en", /never sent to SquadOpt/],
    ["tr", /SquadOpt'a hiç gönderilmez/],
  ] as const)("says in %s that a member's own key never reaches the site", (language, words) => {
    mount(language);
    const llmopt = screen.getByRole("heading", { level: 2, name: "LLMOPT" }).parentElement!;
    expect(within(llmopt).getByText(words)).toBeInTheDocument();
  });

  it("has the same sections in both languages", () => {
    expect(PRIVACY_COPY.tr.sections).toHaveLength(PRIVACY_COPY.en.sections.length);
  });

  it("writes no em dash", () => {
    expect(JSON.stringify(PRIVACY_COPY)).not.toContain("\u2014");
  });
});
