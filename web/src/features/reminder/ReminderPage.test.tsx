/**
 * How notifications are received: the page with the switch, its status word and the three
 * steps with their pictures, in both languages and in each state of the browser.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES } from "../../i18n/messages";
import { AS_A_CHANCE } from "../../testSupport/honesty";
import type { ReminderBrowser } from "./deadlineReminder";
import { ReminderPage } from "./ReminderPage";
import { fakeBrowser } from "./fakeBrowser";

afterEach(cleanup);

const open = (
  browser: ReminderBrowser,
  language: "tr" | "en" = "tr",
  address = "/league/352490/members/35249001/reminder",
) =>
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route
            path="/league/:leagueId/members/:entryId/reminder"
            element={<ReminderPage browser={browser} />}
          />
        </Routes>
      </MemoryRouter>
    </LanguageProvider>,
  );

describe.each(["tr", "en"] as const)("the how-to page in %s", (language) => {
  const copy = MESSAGES[language].reminder;

  it("shows the switch off with its status, and the three steps with a picture each", async () => {
    const { container } = open(fakeBrowser(), language);
    expect(screen.getByRole("heading", { level: 1, name: copy.title })).toBeInTheDocument();
    expect(await screen.findByRole("switch", { name: copy.label })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("status")).toHaveTextContent(copy.statusOff);
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps.map((step) => step.querySelector("h2")?.textContent)).toEqual([
      copy.step1Title,
      copy.step2Title,
      copy.step3Title,
    ]);
    expect(container.querySelectorAll("svg")).toHaveLength(3);
    expect(container.textContent).toContain(copy.allowWord);
    expect(container.textContent).toContain(copy.sampleTitle);
    expect(screen.getByRole("link", { name: copy.back })).toHaveAttribute(
      "href",
      "/league/352490/members/35249001",
    );
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
  });

  it("says the reminder is on where the browser holds one", async () => {
    open(fakeBrowser({ held: true }), language);
    expect(await screen.findByRole("switch", { name: copy.on })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent(copy.statusOn);
  });

  it("says what to do where the browser cannot show notifications, or has refused", async () => {
    open(fakeBrowser({ pushManager: false }), language);
    expect(await screen.findByRole("status")).toHaveTextContent(copy.statusUnsupported);
    cleanup();
    open(fakeBrowser({ permission: "denied" }), language);
    expect(await screen.findByRole("status")).toHaveTextContent(copy.statusDenied);
  });
});

describe("the address", () => {
  it("refuses a team number that is not one", () => {
    open(fakeBrowser(), "tr", "/league/352490/members/abc/reminder");
    expect(screen.getByText(MESSAGES.tr.leagueMembers.invalidEntry)).toBeInTheDocument();
  });
});
