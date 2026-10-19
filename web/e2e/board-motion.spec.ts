import { expect, test, type Page } from "@playwright/test";

import { mockEntryAdviceEnvelope } from "../src/fixtures/league";
import type { AdviceMove, AdvicePlayer } from "../src/features/league/types";
import { installLeagueMocks } from "./leagueMocks";

// The substitution board's motion (#1131) in a real browser: with motion the boards move
// when the decision is drawn, and with the reduced-motion preference nothing moves and the
// boards end exactly as they do with motion, once it has finished.
const ENTRY = 35249001;

function player(id: number, short: string): AdvicePlayer {
  return { player_id: id, name: `Player ${short}`, short_name: short, position: "MID", team: "X" };
}

function move(id: string, out: AdvicePlayer, into: AdvicePlayer, delta: number): AdviceMove {
  return {
    move_id: id,
    player_out: out,
    player_in: into,
    expected_points_delta: delta,
    reason_code: "points_gain",
  };
}

async function openDecision(page: Page) {
  await installLeagueMocks(page);
  await page.route(/\/data\/league\/advice\/35249001\/saf-puan\/1\.json(?:\?.*)?$/, (route) => {
    const envelope = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    envelope.payload.moves = [
      move("gw-1", player(1, "Palmer"), player(2, "Fernandes"), 2.4),
      move("gw-2", player(3, "Jesus"), player(4, "Brobbey"), 0.6),
    ];
    envelope.payload.solver_status = "OPTIMAL";
    envelope.payload.captain = player(5, "Haaland");
    envelope.payload.vice_captain = player(2, "Fernandes");
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(envelope) });
  });
  await page.goto(`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`);
  const boards = page.getByRole("article", { name: /^(Değişiklik|Change) \d+\/\d+$/ });
  await expect(boards.first()).toBeVisible();
  return boards;
}

/** Each board's text, and the opacity and transform of its panels and its gain. */
async function endState(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("article")]
      .filter((board) =>
        /^(Değişiklik|Change) \d+\/\d+$/.test(board.querySelector("h3")?.textContent ?? ""),
      )
      .map((board) => ({
        text: board.textContent,
        parts: [...board.querySelectorAll(":scope > div > div, :scope > p")].map((part) => {
          const style = getComputedStyle(part);
          return [style.opacity, style.transform];
        }),
      })),
  );
}

const boardAnimations = (page: Page) =>
  page.evaluate(
    () =>
      document
        .getAnimations()
        .filter((animation) =>
          (animation.effect as KeyframeEffect | null)?.target?.closest("article"),
        ).length,
  );

test("with motion the boards move, and under reduced motion they end the same without moving", async ({
  browser,
}) => {
  const moving = await browser.newPage();
  await moving.emulateMedia({ reducedMotion: "no-preference" });
  await openDecision(moving);
  expect(await boardAnimations(moving)).toBeGreaterThan(0);
  await expect.poll(() => boardAnimations(moving)).toBe(0);
  const settled = await endState(moving);

  const still = await browser.newPage();
  await still.emulateMedia({ reducedMotion: "reduce" });
  await openDecision(still);
  expect(await boardAnimations(still)).toBe(0);
  const instant = await endState(still);

  expect(instant.length).toBeGreaterThan(0);
  expect(instant).toEqual(settled);
  await moving.close();
  await still.close();
});

test("on a 320 px phone the incoming panel stays inside the board's frame while it moves", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await openDecision(page);
  // The motion held at a few points of its run, the first frame among them, where the
  // incoming panel is furthest to the right; at each, no board is wider than its frame.
  const frames = await page.evaluate(() => {
    const boards = [...document.querySelectorAll("article")].filter((board) =>
      /^(Değişiklik|Change) \d+\/\d+$/.test(board.querySelector("h3")?.textContent ?? ""),
    );
    const moving = document
      .getAnimations()
      .filter((animation) =>
        (animation.effect as KeyframeEffect | null)?.target?.closest("article"),
      );
    for (const animation of moving) animation.pause();
    const widths = [0, 100, 200, 300].map((time) => {
      for (const animation of moving) animation.currentTime = time;
      return boards.map((board) => [board.scrollWidth, board.clientWidth]);
    });
    for (const animation of moving) animation.play();
    return { moving: moving.length, widths };
  });
  expect(frames.moving).toBeGreaterThan(0);
  for (const boards of frames.widths)
    for (const [scrollWidth, clientWidth] of boards) expect(scrollWidth).toBe(clientWidth);
});
