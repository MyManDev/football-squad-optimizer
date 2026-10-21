import { expect, test } from "@playwright/test";
import fixture from "../src/fixtures/device-plan/instances.json" with { type: "json" };
import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../src/fixtures/league";
import { MESSAGES } from "../src/i18n/messages";
import { installLeagueMocks } from "./leagueMocks";

for (const language of ["tr", "en"] as const) {
  test(`one typed rival is read on demand in a 1000-member league (${language})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await installLeagueMocks(page);
    await page.addInitScript((value) => localStorage.setItem("squadopt.language", value), language);
    const ownId = 35249001;
    const own = mockEntrySquadEnvelopes[ownId]!;
    const members = [
      { ...own.payload.entry, rank: 500 },
      ...Array.from({ length: 999 }, (_, i) => ({
        ...own.payload.entry,
        entry_id: 10000 + i,
        rank: i < 499 ? i + 1 : i + 2,
      })),
    ];
    const copy = MESSAGES[language].leagueMembers;
    await page.route(/\/data\/league\/members\.json(?:\?.*)?$/, (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...mockLeagueMembersEnvelope,
          payload: { ...mockLeagueMembersEnvelope.payload, members },
        }),
      }),
    );
    const reads: number[] = [];
    await page.route(/\/data\/league\/entries\/(\d+)\.json(?:\?.*)?$/, (route) => {
      const id = Number(/entries\/(\d+)\.json/.exec(route.request().url())![1]);
      reads.push(id);
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...own,
          payload: {
            ...own.payload,
            entry: members.find((member) => member.entry_id === id),
            source_snapshot_id: fixture.document.source_snapshot_id,
            device_plan: fixture.members[2]!.entry,
          },
        }),
      });
    });
    const index = mockEntryAdviceIndex(ownId);
    Object.assign(index.payload, {
      default_rival_entry_id: null,
      rival_entry_ids: [],
      computed: [],
      unavailable: [],
      strategies: ["saf-puan"],
      windows: { "saf-puan": [1] },
    });
    await page.route(/\/data\/league\/advice\/35249001\/index\.json(?:\?.*)?$/, (route) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(index) }),
    );
    await page.goto(`/league/352490/members/${ownId}?mode=ortak-koru&window=1`);
    const input = page.getByLabel(copy.rivalEntryLabel);
    await expect(input).toBeVisible();
    await expect
      .poll(() => [...new Set(reads)].sort((a, b) => a - b))
      .toEqual([10498, 10499, ownId]);
    await input.fill("10998");
    expect(reads).toHaveLength(3);
    await page.getByRole("button", { name: copy.rivalEntryChoose }).click();
    await expect(page).toHaveURL(/rival=10998/);
    await expect.poll(() => reads).toHaveLength(4);
    expect(reads.at(-1)).toBe(10998);
    await expect(page.getByRole("button", { name: copy.deviceButton })).toBeVisible();
  });
}
