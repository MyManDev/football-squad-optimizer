import { expect, test } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { NO_LEAGUE } from "./leagueState";

// This is the first visit: no league remembered.
test.use({ storageState: NO_LEAGUE });

for (const language of ["tr", "en"] as const) {
  test(`a number the site does not publish is refused after the directory alone in ${language}`, async ({
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
    await expect(page.getByRole("status")).toHaveText(
      language === "tr"
        ? "Bu site 123 numaralı ligi yayımlamıyor."
        : "This site does not publish league 123.",
    );
    await expect(page).toHaveURL("/");
    // Only the directory was read (the absent list, then the legacy tree's record); no
    // document of league 123 was asked for.
    const directory = ["/data/leagues.json", "/data/league/members.json"];
    expect(requests).toEqual(directory);
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
    expect(requests).toEqual([...directory, ...directory, ...directory]);
  });
}
