import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { atRest } from "./atRest";
import { NO_LEAGUE } from "./leagueState";

// This is the first visit: no league remembered.
test.use({ storageState: NO_LEAGUE });

for (const language of ["tr", "en"] as const) {
  test(`a number the site does not publish goes to its own address, read from the forwarder, in ${language}`, async ({
    page,
  }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    let response: "published" | "missing" | "failed" = "published";
    const requests: string[] = [];
    page.on("request", (request) => {
      // The shell's fixture list is site-level and read on every page, whatever is typed here.
      const path = new URL(request.url()).pathname;
      if (["fetch", "xhr"].includes(request.resourceType()) && path !== "/data/fixtures.json") {
        requests.push(path);
      }
    });
    // No directory is published: the one league under data/league/ is the directory.
    await page.route("**/data/leagues.json", (route) => route.fulfill({ status: 404, body: "" }));
    await page.route("**/data/league/members.json", (route) => {
      return route.fulfill(
        response === "published"
          ? {
              contentType: "application/json",
              body: JSON.stringify({ ...mockLeagueMembersEnvelope, source_kind: "live" }),
            }
          : { status: response === "missing" ? 404 : 503, body: "" },
      );
    });
    await page.goto("/");
    const field = page.getByLabel(language === "tr" ? "Lig numarası" : "League ID");
    const submit = page.getByRole("button", {
      name: language === "tr" ? "Ligi bul" : "Find league",
    });
    await field.fill("123");
    await submit.click();
    // Not published: its own address, where the gate asks the forwarder, which this preview
    // does not run, so the league cannot be opened now.
    await expect(page).toHaveURL("/league/123");
    await expect(page.getByRole("status")).toHaveText(
      language === "tr"
        ? "123 numaralı lig şu anda açılamıyor."
        : "League 123 cannot be opened right now.",
    );
    // The directory (the absent list, then the legacy tree's record), read by the form and
    // again by the gate, then page 1 of league 123's standings; no published document of it.
    const directory = ["/data/leagues.json", "/data/league/members.json"];
    const opened = [...directory, ...directory, "/api/v1/fpl/standings/123"];
    expect(requests).toEqual(opened);
    await field.fill("352490");
    response = "missing";
    await submit.click();
    await expect(page.getByRole("status")).toHaveText(
      language === "tr"
        ? "Yayımlanmış lig belgesi şu anda mevcut değil. Daha sonra yeniden dene."
        : "The published league document is unavailable. Try again later.",
    );
    response = "failed";
    await submit.click();
    await expect(page.getByRole("status")).toHaveText(
      language === "tr"
        ? "Yayımlanan lig verisi okunamadı. Yeniden dene."
        : "The published league data could not be read. Try again.",
    );
    expect(requests).toEqual([...opened, ...directory, ...directory]);
  });
}

for (const language of ["tr", "en"] as const) {
  test(`where the league ID is found opens under the field on a 390 px phone in ${language}`, async ({
    page,
  }) => {
    const entry = MESSAGES[language].leagueEntry;
    const copy = MESSAGES[language].fplIdHelp;
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const field = page.getByLabel(entry.label);
    const submit = page.getByRole("button", { name: entry.submit, exact: true });
    const summary = page.locator("summary", { hasText: copy.title });
    const help = page.locator("details", { has: summary });
    // The form's last edge, its button, is on the first screen whether the help is shut or
    // open: the help never sends the field and its action below the fold.
    const onFirstScreen = async () => {
      const box = (await submit.boundingBox())!;
      return box.y + box.height <= 844;
    };
    await expect(help).not.toHaveAttribute("open");
    await expect(field).toBeVisible();
    expect(await onFirstScreen()).toBe(true);
    expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);

    // The summary is the next stop after the field, and opens with the keyboard.
    await field.focus();
    await page.keyboard.press("Tab");
    await expect(summary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(help).toHaveAttribute("open", "");
    await expect(help.getByText(copy.league)).toBeVisible();
    await expect(help.locator("code")).toHaveText(
      "fantasy.premierleague.com/leagues/123456/standings/c",
    );
    const site = help.getByRole("link", {
      name: `fantasy.premierleague.com (${copy.newTab})`,
      exact: true,
    });
    await expect(site).toHaveAttribute("href", "https://fantasy.premierleague.com/");
    await expect(site).toHaveAttribute("target", "_blank");
    await expect(site).toHaveAttribute("rel", "noopener noreferrer");
    expect((await site.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await atRest(page);
    expect(await onFirstScreen()).toBe(true);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);

    const results = await new AxeBuilder({ page }).analyze();
    expect(
      results.violations
        .filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))
        .map((violation) => violation.id),
    ).toEqual([]);

    await page.keyboard.press("Enter");
    await expect(help).not.toHaveAttribute("open");
  });
}
