import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const ROUTES = ["/", "/moves", "/rivals", "/league", "/analysis", "/status"] as const;
const BLOCKING_IMPACTS = new Set(["critical", "serious"]);

async function waitForPage(page: import("@playwright/test").Page) {
  await expect(page.locator("main")).not.toContainText(/Yükleniyor|Loading/);
}

for (const language of ["tr", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test(`axe has no critical or serious violations in ${language} ${theme}`, async ({ page }) => {
      await page.addInitScript(
        ({ selectedLanguage, selectedTheme }) => {
          localStorage.setItem("squadopt.language", selectedLanguage);
          localStorage.setItem("squadopt.theme", selectedTheme);
        },
        { selectedLanguage: language, selectedTheme: theme },
      );

      for (const route of ROUTES) {
        await page.goto(route);
        await waitForPage(page);
        const results = await new AxeBuilder({ page }).analyze();
        const blocking = results.violations.filter((violation) =>
          BLOCKING_IMPACTS.has(violation.impact ?? ""),
        );
        const summary = blocking.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          nodes: violation.nodes.length,
          targets: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
        }));
        expect(summary, `${language} ${theme} ${route}`).toEqual([]);
      }
    });
  }
}

test("language controls satisfy label-in-name and remain keyboard operable", async ({ page }) => {
  await page.goto("/");
  const turkish = page.getByRole("button", { name: /^TR/ });
  const english = page.getByRole("button", { name: /^EN/ });

  await expect(turkish).toHaveText("TR");
  await expect(english).toHaveText("EN");
  await english.focus();
  await page.keyboard.press("Enter");
  await expect(english).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("skip link and primary navigation expose visible keyboard focus", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");

  const skip = page.getByRole("link", { name: "İçeriğe geç" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await expect(skip).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Tab");
  const squad = page.getByRole("link", { name: "Kadro", exact: true });
  await expect(squad).toBeFocused();
  await expect(squad).toHaveCSS("outline-style", "solid");

  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Önerilen hamleler" })).toBeFocused();
});
