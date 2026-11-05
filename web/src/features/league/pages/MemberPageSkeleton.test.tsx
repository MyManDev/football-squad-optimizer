import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { MemberPageSkeleton } from "./MemberPageSkeleton";

afterEach(cleanup);

describe("the member page's skeleton", () => {
  it.each(["tr", "en"] as const)(
    "is a busy status that says in %s what it waits for, its blocks hidden",
    (language: Language) => {
      const { container } = render(
        <LanguageProvider initialLanguage={language}>
          <MemberPageSkeleton />
        </LanguageProvider>,
      );
      const status = screen.getByRole("status");
      expect(status).toHaveAttribute("aria-busy", "true");
      expect(status).toHaveTextContent(MESSAGES[language].leagueMembers.loadingEntry);
      expect(screen.getByText(MESSAGES[language].leagueMembers.loadingEntry)).toHaveClass(
        "visually-hidden",
      );
      // The top bar with its figures, the decision and the pitch, none of them read out.
      const shapes = container.querySelectorAll('[aria-hidden="true"]');
      expect(shapes).toHaveLength(3);
      expect(shapes[0]!.querySelectorAll(".scoreCell")).toHaveLength(5);
      expect(container.querySelector(".pitch")).not.toBeNull();
    },
  );

  it("never moves, so a page waiting on it is at rest", () => {
    const css = readFileSync(join(__dirname, "MemberPageSkeleton.module.css"), "utf-8").replace(
      /\/\*[\s\S]*?\*\//g,
      "",
    );
    expect(css).not.toMatch(/animation|transition|@keyframes/);
  });
});
