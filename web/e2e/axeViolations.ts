import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import axe from "axe-core";

declare global {
  interface Window {
    axe?: typeof axe;
  }
}

/** Keep the partial audit and its report in one document when there are no child frames. */
export async function axeViolations(page: Page, rules?: string[]) {
  if (page.frames().length === 1) {
    if ((await page.evaluate(() => window.axe?.version)) !== axe.version) {
      await page.evaluate(axe.source);
    }
    const violations = await page.evaluate(async (rules) => {
      const engine = window.axe!;
      const options: axe.RunOptions = { resultTypes: ["violations"] };
      if (rules) options.runOnly = { type: "rule", values: rules };
      engine.configure({
        allowedOrigins: ["<same_origin>"],
        branding: { application: "playwright" },
      });
      const partial = await engine.runPartial({ include: [], exclude: [] }, options);
      // A frame can appear after the initial Playwright frame count.
      if (partial.frames.length) return null;
      return (await engine.finishRun([partial], options)).violations;
    }, rules);
    if (violations !== null) return violations;
  }

  const builder = new AxeBuilder({ page });
  if (rules) builder.withRules(rules);
  return (await builder.analyze()).violations;
}
