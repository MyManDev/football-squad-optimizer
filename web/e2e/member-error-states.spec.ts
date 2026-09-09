import { expect, test } from "@playwright/test";

import { mockEntryAdviceEnvelope, mockEntryAdviceIndex } from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

const ENTRY = 35249001;
const failures = [
  "list-missing",
  "list-error",
  "list-shape",
  "member-missing",
  "member-error",
  "member-shape",
  "index-missing",
  "index-error",
  "declared-unavailable",
  "listed-missing",
  "listed-error",
  "listed-json",
  "listed-shape",
  "context-mismatch",
] as const;

for (const language of ["tr", "en"] as const) {
  for (const failure of failures) {
    test(`published ${failure} stays truthful in ${language}`, async ({ page }) => {
      const copy = MESSAGES[language].leagueMembers;
      await page.addInitScript(
        (value) => localStorage.setItem("squadopt.language", value),
        language,
      );
      await installLeagueMocks(page);
      const browserErrors: string[] = [];
      page.on("pageerror", (error) => browserErrors.push(error.message));
      const planReads: string[] = [];
      page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (path.includes(`/data/league/advice/${ENTRY}/`) && !path.endsWith("index.json"))
          planReads.push(path);
      });
      let path: string;
      let status = 200;
      let body: string;
      let expected: string;
      if (failure.startsWith("list-")) {
        path = "members.json";
        status = failure === "list-missing" ? 404 : failure === "list-error" ? 503 : 200;
        body = JSON.stringify({
          contract_version: "provisional_league_ui_v1",
          source_kind: "live",
          generated_at_utc: "2026-09-09T00:00:00Z",
          payload: null,
        });
        expected = failure === "list-missing" ? copy.notAvailable : copy.membersUnreadable;
      } else if (failure.startsWith("member-")) {
        path = `entries/${ENTRY}.json`;
        status = failure === "member-missing" ? 404 : failure === "member-error" ? 503 : 200;
        body = JSON.stringify({
          contract_version: "provisional_league_ui_v1",
          source_kind: "live",
          generated_at_utc: "2026-09-09T00:00:00Z",
          payload: {},
        });
        expected = failure === "member-missing" ? copy.entryNotAvailable : copy.entryUnreadable;
      } else if (failure.startsWith("index-") || failure === "declared-unavailable") {
        path = `advice/${ENTRY}/index.json`;
        const index = structuredClone(mockEntryAdviceIndex(ENTRY));
        if (failure === "declared-unavailable") {
          index.payload.unavailable.push({
            strategy: "saf-puan",
            window: 1,
            rival_entry_id: null,
            reason: "__proto__",
          });
        }
        status = failure === "index-missing" ? 404 : failure === "index-error" ? 503 : 200;
        body = JSON.stringify(index);
        expected =
          copy.publicationStates[
            failure as "index-missing" | "index-error" | "declared-unavailable"
          ].title;
      } else {
        path = `advice/${ENTRY}/saf-puan/1.json`;
        const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
        if (failure === "context-mismatch") advice.payload.gameweek += 1;
        if (failure === "listed-shape")
          advice.payload.moves = null as unknown as typeof advice.payload.moves;
        status = failure === "listed-missing" ? 404 : failure === "listed-error" ? 503 : 200;
        body = failure === "listed-json" ? '{"payload":' : JSON.stringify(advice);
        expected =
          failure === "listed-missing"
            ? copy.publicationStates["published-missing"].title
            : failure === "context-mismatch"
              ? copy.publicationStates["context-mismatch"].title
              : copy.adviceUnreadable;
      }
      await page.route(`**/data/league/${path}`, (route) =>
        route.fulfill({ status, contentType: "application/json", body }),
      );
      await page.goto(failure.startsWith("list-") ? "/league/members" : `/league/members/${ENTRY}`);
      await expect(page.getByText(expected, { exact: true })).toBeVisible();
      if (
        failure.startsWith("index-") ||
        failure.startsWith("listed-") ||
        failure === "declared-unavailable" ||
        failure === "context-mismatch"
      ) {
        await expect(
          page.getByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
        ).toBeVisible();
      }
      if (failure.startsWith("index-") || failure === "declared-unavailable") {
        expect(planReads).toEqual([]);
        await expect(page.getByRole("button", { name: copy.computeButton })).toBeDisabled();
      }
      if (failure.startsWith("listed-")) {
        await expect(
          page.getByText(copy.publicationStates["declared-unavailable"].title),
        ).toHaveCount(0);
        await expect(page.getByText(copy.adviceNotComputed)).toHaveCount(0);
      }
      if (failure === "declared-unavailable") {
        await expect(page.getByText(copy.publicationReasonUnknown)).toBeVisible();
        await expect(page.locator("main")).not.toContainText("__proto__");
      }
      expect(browserErrors).toEqual([]);
    });
  }
}
