/**
 * The reminder's switch: off to on asks the browser and opens the how-to page; on to off
 * drops the reminder in place; a browser that cannot hold one, or has refused, keeps the
 * switch off and opens the page.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES } from "../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../testSupport/honesty";
import type { ReminderBrowser } from "./deadlineReminder";
import { fakeBrowser } from "./fakeBrowser";
import { ReminderSwitch } from "./ReminderSwitch";

afterEach(cleanup);

const TARGET = { leagueId: 352490, entryId: 35249001, language: "tr" as const };
function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}</output>;
}

const open = (browser: ReminderBrowser, language: "tr" | "en" = "tr") =>
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/league/352490/members/35249001"]}>
        <Routes>
          <Route path="*" element={<ReminderSwitch target={TARGET} browser={browser} />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </LanguageProvider>,
  );

describe.each(["tr", "en"] as const)("the reminder's switch in %s", (language) => {
  const copy = MESSAGES[language].reminder;

  it("is off, and on a flip asks the browser, turns on and opens the how-to page", async () => {
    const browser = fakeBrowser();
    const { container } = open(browser, language);
    const control = await screen.findByRole("switch", { name: copy.label });
    expect(control).toHaveAttribute("aria-checked", "false");
    await userEvent.click(control);
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: copy.on })).toHaveAttribute("aria-checked", "true"),
    );
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/league/352490/members/35249001/reminder",
    );
    expect(browser.requests).toEqual(["GET /api/v1/push/key", "PUT /api/v1/push/subscriptions"]);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("is on where the browser holds a subscription, and a flip turns it off in place", async () => {
    const browser = fakeBrowser({ held: true });
    open(browser, language);
    const control = await screen.findByRole("switch", { name: copy.on });
    await userEvent.click(control);
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: copy.label })).toHaveAttribute(
        "aria-checked",
        "false",
      ),
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/league/352490/members/35249001");
    expect(screen.getByTestId("where")).not.toHaveTextContent("/reminder");
    expect(browser.requests).toEqual(["DELETE /api/v1/push/subscriptions"]);
  });
});

describe("where the browser cannot hold a reminder", () => {
  it("stays off and opens the how-to page, asking the browser nothing", async () => {
    const browser = fakeBrowser({ pushManager: false });
    open(browser);
    const control = await screen.findByRole("switch", { name: "Hatırlatma" });
    expect(control).toHaveAttribute("data-reminder", "unsupported");
    await userEvent.click(control);
    expect(screen.getByTestId("where")).toHaveTextContent("/reminder");
    expect(browser.requests).toEqual([]);
    expect(control).toHaveAttribute("aria-checked", "false");
  });

  it("stays off where notifications were refused, and opens the page", async () => {
    const browser = fakeBrowser({ permission: "denied" });
    open(browser);
    const control = await screen.findByRole("switch", { name: "Hatırlatma" });
    expect(control).toHaveAttribute("data-reminder", "denied");
    await userEvent.click(control);
    expect(screen.getByTestId("where")).toHaveTextContent("/reminder");
    expect(browser.requests).toEqual([]);
  });
});
