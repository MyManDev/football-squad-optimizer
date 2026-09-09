import { expect, test } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";

for (const language of ["tr", "en"] as const) {
  test(`the league allowlist rejects unsupported IDs without fetching in ${language}`, async ({
    page,
  }) => {
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    let response: "published" | "missing" | "failed" = "published";
    const requests: string[] = [];
    page.on("request", (request) => {
      if (["fetch", "xhr"].includes(request.resourceType())) {
        requests.push(new URL(request.url()).pathname);
      }
    });
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
        ? "Şimdilik yalnız 352490 numaralı lig destekleniyor."
        : "Only league 352490 is supported for now.",
    );
    await expect(page).toHaveURL("/");
    expect(requests).toEqual([]);
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
    expect(requests).toEqual(Array(2).fill("/data/league/members.json"));
  });
}
