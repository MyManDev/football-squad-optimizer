import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { heldChips } from "../src/features/league/device/chipForecast/member";
import type { EntrySquad } from "../src/features/league/types";
import { MESSAGES } from "../src/i18n/messages";
import { PUBLIC_ROOT, shippedTrees } from "../src/testSupport/shippedTrees";
import { atRest } from "./atRest";
import { claimMember, shippedClaim, type SeededClaim } from "./identity";

// The chip timing card (#1003) in a real browser: the plain plan and each held chip solved
// in the device's worker, the reading made on the page from the documents the site
// serves, and the card drawn beside the chip control. Once on the shipped tree, for every
// member, and once on a league tree that is not 352490 and publishes no advice index,
// where the device is the only source the card has. From the press on, nothing leaves the
// site's origin.

const COPY = MESSAGES.tr.leagueMembers;
const read = <T>(path: string): T => JSON.parse(readFileSync(path, "utf-8")) as T;

interface Published {
  status: string;
  forecast: { chips: { name: string; verdict: string }[] } | null;
}

/** The first tree the site ships and its members with device inputs, with their readings. */
function shippedMembers() {
  const tree = shippedTrees()[0]!;
  const members = readdirSync(join(tree.root, "entries")).flatMap((name) => {
    const match = /^(\d+)\.json$/.exec(name);
    if (!match) return [];
    const squad = read<{ payload: EntrySquad }>(join(tree.root, "entries", name)).payload;
    if (!squad.device_plan) return [];
    const index = join(tree.root, "advice", match[1]!, "index.json");
    const published = existsSync(index)
      ? (read<{ payload: { chip_forecast?: Published } }>(index).payload.chip_forecast ?? null)
      : null;
    // The chips the device solves beside the plain plan: n of the 1 + n solves.
    const held = heldChips(squad.chips, squad.gameweek)?.length ?? 0;
    return [{ entryId: Number(match[1]), published, held }];
  });
  return { tree, members };
}

/** The chips the published reading names to play or hold, in its order. */
function shownChips(published: Published | null): string[] {
  if (published?.status !== "available") return [];
  return (published.forecast?.chips ?? [])
    .filter((chip) => chip.verdict === "play_now" || chip.verdict === "hold")
    .map((chip) => chip.name);
}

/** A moment the shipped gameweek is still open: a day before its deadline. */
function beforeDeadline(gameweek: number): Date {
  const calendar = read<{ payload: { gameweeks: { gameweek: number; deadline_utc: string }[] } }>(
    join(PUBLIC_ROOT, "data", "fixtures.json"),
  ).payload;
  const deadline = calendar.gameweeks.find((week) => week.gameweek === gameweek)!.deadline_utc;
  return new Date(Date.parse(deadline) - 24 * 60 * 60 * 1000);
}

async function openPage(page: Page, claim: SeededClaim, gameweek: number): Promise<void> {
  await page.clock.setFixedTime(beforeDeadline(gameweek));
  await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
  await claimMember(page, claim);
  // Each reply the worker posts, with its own solving time and the moment the page got it,
  // and each press. The fixed clock stands in for the page's User Timing, so the page's
  // measures cannot be read; an event's own time stamp is not the clock's.
  await page.addInitScript(() => {
    const replies: { kind: string; seconds: number | null; at: number }[] = [];
    const presses: number[] = [];
    Object.assign(window, { deviceReplies: replies, devicePresses: presses });
    document.addEventListener("click", (event) => presses.push(event.timeStamp), true);
    const Original = window.Worker;
    window.Worker = class extends Original {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options);
        this.addEventListener("message", (event: MessageEvent) => {
          const data = event.data as {
            kind: string;
            seconds?: number;
            answer?: { seconds?: number };
          };
          const seconds = data.answer?.seconds ?? data.seconds ?? null;
          replies.push({ kind: data.kind, seconds, at: event.timeStamp });
        });
      }
    };
  });
}

/** One device run: its plain plan, then its gains, each from the press and by the worker. */
interface Run {
  requested: string[];
  /** The worker's solving time for the plain plan, and for the whole run. */
  planSeconds: number;
  gainsSeconds: number | null;
  /** From the press to the plan's arrival on the page, and to the gains'. */
  planArrival: number;
  gainsArrival: number | null;
}

/**
 * Opens a member's one-week plan, presses compute on this device, waits for the plan and
 * then for the end of the run, and returns every request made from the press on.
 */
async function solve(page: Page, address: string): Promise<Run> {
  const requested: string[] = [];
  let pressed = false;
  const listen = (request: { url(): string }) => {
    if (pressed) requested.push(request.url());
  };
  page.on("request", listen);
  await page.goto(address);
  const button = page.getByRole("button", { name: COPY.deviceButton });
  await expect(button).toBeVisible();
  pressed = true;
  await button.click();
  await expect(page.locator("[data-device-state='done']")).toBeVisible({ timeout: 120_000 });
  // The run ends with its gains, or with its one answer where it asked for none.
  await page.waitForFunction(
    () =>
      (window as unknown as { deviceReplies: { kind: string }[] }).deviceReplies.some(
        (reply) => reply.kind === "gains" || reply.kind === "answer",
      ),
    undefined,
    { timeout: 120_000 },
  );
  page.off("request", listen);
  return {
    requested,
    ...(await page.evaluate(() => {
      const { deviceReplies: replies, devicePresses: presses } = window as unknown as {
        deviceReplies: { kind: string; seconds: number | null; at: number }[];
        devicePresses: number[];
      };
      const press = presses.at(-1)!;
      const plan = replies.find((reply) => reply.kind === "plan" || reply.kind === "answer")!;
      const gains = replies.find((reply) => reply.kind === "gains") ?? null;
      const round = (seconds: number) => Math.round(seconds * 1000) / 1000;
      return {
        planSeconds: round(plan.seconds!),
        gainsSeconds: gains?.seconds == null ? null : round(gains.seconds),
        planArrival: round((plan.at - press) / 1000),
        gainsArrival: gains === null ? null : round((gains.at - press) / 1000),
      };
    })),
  };
}

/** The settings tool that holds the chip control, opened. */
async function openChipSettings(page: Page) {
  const tool = page.locator("details").filter({ hasText: COPY.advancedSettings });
  await tool.locator("summary").first().click();
  return tool;
}

test("every shipped member's chip timing is read on the device, beside the chip control", async ({
  page,
}) => {
  test.setTimeout(600_000);
  const { tree, members } = shippedMembers();
  const claim = shippedClaim();
  const gameweek = read<{ payload: { gameweek: number } }>(join(tree.root, "members.json")).payload
    .gameweek;
  expect(members.length).toBeGreaterThan(0);
  await openPage(page, claim, gameweek);
  const timings: ({ entry: number; chips: number } & Omit<Run, "requested">)[] = [];
  let scanned = false;
  for (const { entryId, published, held } of members) {
    const { requested, ...run } = await solve(
      page,
      `/league/${claim.leagueId}/members/${entryId}?mode=saf-puan&window=1`,
    );
    const origin = new URL(page.url()).origin;
    expect(requested.filter((url) => new URL(url).origin !== origin)).toEqual([]);
    const expected = shownChips(published);
    const tool = await openChipSettings(page);
    const card = tool.locator("[data-chip-timing]");
    if (expected.length === 0) {
      await expect(card).toHaveCount(0);
    } else {
      await expect(card.getByRole("heading", { name: "Çip zamanı" })).toBeVisible();
      await expect(card.locator("[data-chip]")).toHaveCount(expected.length);
      const names = await card
        .locator("[data-chip]")
        .evaluateAll((rows) => rows.map((row) => row.getAttribute("data-chip")));
      expect(names, String(entryId)).toEqual(expected);
      if (!scanned) {
        await atRest(page);
        const results = await new AxeBuilder({ page }).include("[data-chip-timing]").analyze();
        expect(results.violations).toEqual([]);
        scanned = true;
      }
    }
    timings.push({ entry: entryId, chips: held, ...run });
  }
  const summary = (values: (number | null)[]) => {
    const sorted = values.filter((value) => value !== null).sort((a, b) => a - b);
    const middle = sorted.length / 2;
    const median =
      sorted.length % 2 === 1
        ? sorted[Math.floor(middle)]!
        : (sorted[middle - 1]! + sorted[middle]!) / 2;
    return { median: Number(median.toFixed(2)), maximum: Number(sorted.at(-1)!.toFixed(2)) };
  };
  // One JSON line with each member's run: the plain plan, then the 1 + n solves' gains, by
  // the worker's count and from the press. It asserts nothing.
  console.log(
    JSON.stringify({
      chipTimingRuns: timings,
      planSeconds: summary(timings.map((row) => row.planSeconds)),
      gainsSeconds: summary(timings.map((row) => row.gainsSeconds)),
      planArrival: summary(timings.map((row) => row.planArrival)),
      gainsArrival: summary(timings.map((row) => row.gainsArrival)),
    }),
  );
});

// A league tree that is not 352490: the shipped tree's members, entries and table under
// another league number, with no advice index and none of the advice documents. The page
// then has no published plan, and the card no published reading, for any member.
const FIXTURE_LEAGUE = 900001;

test("a league tree with no advice index shows the card from the device alone", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const { tree, members } = shippedMembers();
  const directory = read<{
    payload: { leagues: { league_id: number; path: string }[] };
  }>(join(PUBLIC_ROOT, "data", "leagues.json"));
  const line = directory.payload.leagues.find((league) => `data/${league.path}` === tree.path)!;
  const roster = read<{
    payload: {
      gameweek: number;
      league_name: string;
      members: { member_kind: string; entry_id: number; manager_name: string; team_name: string }[];
    };
  }>(join(tree.root, "members.json")).payload;
  // The member with the most chips the published reading names, so the card has rows.
  const chosen = [...members].sort(
    (a, b) => shownChips(b.published).length - shownChips(a.published).length,
  )[0]!;
  expect(shownChips(chosen.published).length).toBeGreaterThan(0);
  const person = roster.members.find((member) => member.entry_id === chosen.entryId)!;
  await openPage(
    page,
    {
      leagueId: FIXTURE_LEAGUE,
      entryId: chosen.entryId,
      managerName: person.manager_name,
      teamName: person.team_name,
      leagueName: "Fixture league",
    },
    roster.gameweek,
  );
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...directory,
        payload: {
          leagues: [
            {
              ...line,
              league_id: FIXTURE_LEAGUE,
              league_name: "Fixture league",
              path: `leagues/${FIXTURE_LEAGUE}`,
            },
          ],
        },
      }),
    }),
  );
  const asked: string[] = [];
  await page.route(new RegExp(`/data/leagues/${FIXTURE_LEAGUE}/([^?]+)`), (route) => {
    const relative = new URL(route.request().url()).pathname.split(
      `/data/leagues/${FIXTURE_LEAGUE}/`,
    )[1]!;
    asked.push(relative);
    const served =
      relative === "members.json" ||
      relative === "device-plan.json" ||
      /^entries\/\d+\.json$/.test(relative);
    const path = join(tree.root, ...relative.split("/"));
    if (!served || relative.includes("..") || !existsSync(path)) {
      return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    }
    const envelope = read<{ payload: Record<string, unknown> }>(path);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...envelope,
        payload: { ...envelope.payload, league_id: FIXTURE_LEAGUE },
      }),
    });
  });

  const { requested } = await solve(
    page,
    `/league/${FIXTURE_LEAGUE}/members/${chosen.entryId}?mode=saf-puan&window=1`,
  );
  const origin = new URL(page.url()).origin;
  expect(requested.length).toBeGreaterThan(0);
  expect(requested.filter((url) => new URL(url).origin !== origin)).toEqual([]);
  // The tree was asked for its advice index and has none; nothing of 352490's was read.
  expect(asked.some((path) => path.startsWith("advice/"))).toBe(true);
  expect(requested.filter((url) => url.includes("/data/leagues/352490/"))).toEqual([]);
  const tool = await openChipSettings(page);
  const card = tool.locator("[data-chip-timing]");
  await expect(card.getByRole("heading", { name: "Çip zamanı" })).toBeVisible();
  await expect(card.locator("[data-chip]")).toHaveCount(shownChips(chosen.published).length);
  await atRest(page);
  const results = await new AxeBuilder({ page }).include("[data-chip-timing]").analyze();
  expect(results.violations).toEqual([]);
});
