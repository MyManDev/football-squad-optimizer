import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { FplIdHelp } from "./FplIdHelp";

afterEach(cleanup);

function show(language: "tr" | "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <FplIdHelp />
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("where an FPL ID is found, in %s", (language) => {
  const copy = MESSAGES[language].fplIdHelp;

  it("is a closed disclosure whose summary asks the question", async () => {
    show(language);
    const summary = screen.getByText(copy.title);
    expect(summary.tagName).toBe("SUMMARY");
    const help = summary.closest("details")!;
    expect(help.open).toBe(false);
    // The chevron is drawn, not read: the question is the summary's whole name.
    expect(summary.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    await userEvent.setup().click(summary);
    expect(help.open).toBe(true);
  });

  it("reads the league ID from the league's address, the number set apart", () => {
    show(language);
    const help = screen.getByText(copy.title).closest("details")!;
    expect(help).toHaveTextContent(copy.league);
    const address = help.querySelector("code")!;
    expect(address).toHaveTextContent("fantasy.premierleague.com/leagues/123456/standings/c");
    expect(address.querySelector("strong")).toHaveTextContent(/^123456$/);
    expect(help).not.toHaveTextContent("/entry/");
  });

  it("links to the FPL site as a plain link that opens a new tab and says so", () => {
    show(language);
    // The disclosure is closed, so the link is found among hidden content too.
    const link = screen.getByRole("link", { hidden: true });
    expect(link).toHaveAttribute("href", "https://fantasy.premierleague.com/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAccessibleName(`fantasy.premierleague.com (${copy.newTab})`);
    expect(link.querySelector("img")).toBeNull();
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
