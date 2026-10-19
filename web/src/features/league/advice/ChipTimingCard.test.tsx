/**
 * The chip timing card: a row for each chip the member holds in the current half, one chip
 * to a gameweek, the expected points it adds, the Triple Captain's player by name, and
 * nothing at all where the reading is refused, no chip is held or the device has not run.
 * Its words, rendered, carry no chance and no caveat in either language, here and for
 * every member of every tree the site ships.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { PUBLIC_ROOT, shippedTrees } from "../../../testSupport/shippedTrees";
import type { Fixture, FixturesPayload } from "../../fixtures/types";
import { memberChipForecast } from "../device/chipForecast/member";
import type { ChipName } from "../device/chipForecast/rule";
import { isDevicePlanDocument, isDevicePlanEntry, type DevicePlanDocument } from "../device/types";
import type { DeviceChipTiming } from "../device/useDevicePlan";
import type {
  ChipWindowState,
  EntryAdviceIndex,
  EntrySquad,
  EntrySquadPlayer,
  LeagueViewEnvelope,
} from "../types";
import { ChipTimingCard } from "./ChipTimingCard";

afterEach(cleanup);

const CAPTURE = "fpl-live-20261009T060000Z-0123456789ab";
const club = (id: number) => `Club ${id}`;

function fixture(id: number, home: number, away: number): Fixture {
  const team = (id: number) => ({ team_id: id, name: club(id), short_name: `C${id}` });
  return {
    fixture_id: id,
    kickoff_utc: null,
    home: team(home),
    away: team(away),
    finished: false,
    home_score: null,
    away_score: null,
  };
}

/**
 * Twenty clubs once a week, except gameweek 12, where clubs 1, 12, 13 and 20 play twice:
 * the captain's club and two of the bench's.
 */
function calendar(): FixturesPayload {
  return {
    season: "2026-27",
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-09T06:00:00Z",
    current_gameweek: 10,
    unscheduled_count: 0,
    gameweeks: Array.from({ length: 38 }, (_, index) => {
      const gameweek = index + 1;
      const fixtures = Array.from({ length: 10 }, (_, pair) =>
        fixture(gameweek * 100 + pair, pair * 2 + 1, pair * 2 + 2),
      );
      if (gameweek === 12) fixtures.push(fixture(1290, 1, 12), fixture(1291, 13, 20));
      return { gameweek, deadline_utc: "2026-10-10T10:00:00Z", fixtures };
    }),
  };
}

function window(state: ChipWindowState["state"], start: number, stop: number): ChipWindowState {
  return { state, gameweek: state === "used" ? start : null, start_event: start, stop_event: stop };
}

/**
 * Gameweek 10. Players 101 to 115 at clubs 1 to 15; 101 is the captain at 5 points, the
 * rest of the eleven at 2 and the bench at 1.5. Every first-half chip is held.
 */
function squad(): EntrySquad {
  const ids = Array.from({ length: 15 }, (_, index) => 101 + index);
  const player = (id: number) =>
    ({
      player_id: id,
      name: id === 101 ? "Ada Keel" : `Player ${id}`,
      short_name: `P${id}`,
      is_captain: id === 101,
    }) as unknown as EntrySquadPlayer;
  return {
    league_id: 900001,
    season: "2026-27",
    gameweek: 10,
    entry: { member_kind: "human", entry_id: 4242 },
    starting_xi: ids.slice(0, 11).map(player),
    bench: ids.slice(11).map(player),
    source_snapshot_id: CAPTURE,
    chips: {
      known: true,
      gameweek: 10,
      states: {
        wildcard: {
          first_half: window("available", 2, 19),
          second_half: window("not_yet", 20, 38),
        },
        freehit: { first_half: window("available", 2, 19), second_half: window("not_yet", 20, 38) },
        bboost: { first_half: window("available", 1, 19), second_half: window("not_yet", 20, 38) },
        "3xc": { first_half: window("available", 1, 19), second_half: window("not_yet", 20, 38) },
      },
    },
  } as unknown as EntrySquad;
}

function timing(gains: DeviceChipTiming["gains"], snapshot = CAPTURE): DeviceChipTiming {
  const ids = Array.from({ length: 15 }, (_, index) => 101 + index);
  return {
    table: {
      season: "2026-27",
      gameweek: 10,
      source_snapshot_id: snapshot,
      players: ids.map((id, index) => ({
        id,
        name: `Table ${id}`,
        team: club(index + 1),
        position: index === 0 ? "GK" : "MID",
        expected_points: index === 0 ? 5 : index < 11 ? 2 : 1.5,
      })),
    } as unknown as DevicePlanDocument,
    gains,
  };
}

const GAINS = { wildcard: 11, freehit: 11, bboost: 3, "3xc": 4 };

function card(
  language: Language,
  props: Partial<Parameters<typeof ChipTimingCard>[0]> = {},
): HTMLElement {
  return render(
    <LanguageProvider initialLanguage={language}>
      <ChipTimingCard squad={squad()} timing={timing(GAINS)} fixtures={calendar()} {...props} />
    </LanguageProvider>,
  ).container;
}

/** Each row's chip and text, as a reader meets them. */
function rows(container: HTMLElement): string[][] {
  return [...container.querySelectorAll("[data-chip]")].map((row) => [
    row.getAttribute("data-chip")!,
    row.querySelector("dt")!.textContent!,
    row.querySelector("dd")!.textContent!,
  ]);
}

describe("the chip timing card", () => {
  it("names this week, a gameweek with its points, the captain, and the window's last gameweek", () => {
    const english = card("en");
    expect(english.querySelector("h3")?.textContent).toBe("Chip timing");
    // Wildcard and Free Hit both clear their thresholds; Wildcard by more keeps this week.
    // Triple Captain keeps gameweek 12 and Bench Boost moves on to gameweek 14.
    expect(rows(english)).toEqual([
      ["wildcard", "Wildcard", "This week, +11.0 xP"],
      ["freehit", "Free Hit", "Not this week, until gameweek 19"],
      ["bboost", "Bench Boost", "Gameweek 14, +6.0 xP"],
      ["3xc", "Triple Captain", "Gameweek 12, +10.0 xP Ada Keel as captain"],
    ]);
    cleanup();
    const turkish = card("tr");
    expect(turkish.querySelector("h3")?.textContent).toBe("Çip zamanı");
    expect(rows(turkish)).toEqual([
      ["wildcard", "Wildcard", "Bu hafta, +11,0 xP beklenen puan"],
      ["freehit", "Free Hit", "Bu hafta değil, 19. haftaya kadar"],
      ["bboost", "Bench Boost", "14. hafta, +6,0 xP beklenen puan"],
      ["3xc", "Triple Captain", "12. hafta, +10,0 xP beklenen puan kaptan Ada Keel"],
    ]);
  });

  it("has no row for a chip whose gain this week is unknown", () => {
    const container = card("en", { timing: timing({ bboost: 3, "3xc": null }) });
    expect(rows(container).map(([name]) => name)).toEqual(["bboost"]);
  });

  it("draws nothing for a refused reading", () => {
    const refused = timing(GAINS, "fpl-live-another-capture");
    expect(
      memberChipForecast({
        table: refused.table,
        squad: squad(),
        fixtures: calendar(),
        gains: GAINS,
      }).status,
    ).toBe("unavailable");
    for (const language of ["en", "tr"] as const) {
      expect(card(language, { timing: refused }).innerHTML).toBe("");
      cleanup();
      expect(card(language, { fixtures: null }).innerHTML).toBe("");
      cleanup();
    }
  });

  it("draws nothing where no chip is held, the history is unknown or the device has not run", () => {
    const spent = squad();
    for (const halves of Object.values(spent.chips!.states)) halves!.first_half!.state = "used";
    const unknown = squad();
    unknown.chips!.known = false;
    for (const props of [{ squad: spent }, { squad: unknown }, { timing: null }]) {
      expect(card("en", props).innerHTML).toBe("");
      cleanup();
    }
  });

  it("says no chance and no caveat in either language", () => {
    for (const language of ["en", "tr"] as const) {
      for (const gains of [GAINS, { bboost: 30, "3xc": 30 }, { wildcard: 1, freehit: 1 }]) {
        const text = card(language, { timing: timing(gains) }).textContent ?? "";
        expect(text.length).toBeGreaterThan(0);
        expect(text).not.toMatch(AS_A_CHANCE);
        expect(text).not.toMatch(AS_A_CAVEAT);
        cleanup();
      }
    }
  });
});

const read = <T,>(path: string): T => JSON.parse(readFileSync(path, "utf-8")) as T;

/** Every shipped member with device inputs and a published reading, with its published gains. */
function shippedMembers() {
  const fixtures = read<LeagueViewEnvelope<FixturesPayload>>(
    join(PUBLIC_ROOT, "data", "fixtures.json"),
  ).payload;
  const found: {
    entryId: number;
    squad: EntrySquad;
    table: DevicePlanDocument;
    gains: Partial<Record<ChipName, number | null>>;
    rows: number;
  }[] = [];
  for (const { root } of shippedTrees()) {
    if (!existsSync(join(root, "advice"))) continue;
    const table = read<LeagueViewEnvelope<unknown>>(join(root, "device-plan.json")).payload;
    if (!isDevicePlanDocument(table)) continue;
    for (const name of readdirSync(join(root, "entries"))) {
      const match = /^(\d+)\.json$/.exec(name);
      const indexPath = join(root, "advice", match?.[1] ?? "", "index.json");
      if (!match || !existsSync(indexPath)) continue;
      const squad = read<LeagueViewEnvelope<EntrySquad>>(join(root, "entries", name)).payload;
      if (!isDevicePlanEntry(squad.device_plan)) continue;
      const index = read<LeagueViewEnvelope<EntryAdviceIndex>>(indexPath).payload;
      const published = index.chip_forecast as {
        forecast: { chips: { verdict: string }[] } | null;
      } | null;
      const gains: Partial<Record<ChipName, number | null>> = {};
      for (const [chip, path] of Object.entries(index.chips?.available ? index.chips.paths : {})) {
        const gain = read<LeagueViewEnvelope<{ chip_choice?: { gain_vs_no_chip?: unknown } }>>(
          join(root, path),
        ).payload.chip_choice?.gain_vs_no_chip;
        gains[chip as ChipName] = typeof gain === "number" ? gain : null;
      }
      const shown = (published?.forecast?.chips ?? []).filter(
        (chip) => chip.verdict === "play_now" || chip.verdict === "hold",
      ).length;
      found.push({ entryId: Number(match[1]), squad, table, gains, rows: shown });
    }
  }
  return { fixtures, members: found };
}

describe("the chip timing card on the shipped trees", () => {
  const { fixtures, members } = shippedMembers();

  it("has members to read", () => {
    expect(members.length).toBeGreaterThan(0);
  });

  for (const language of ["en", "tr"] as const) {
    it(`draws a row for each published chip to play or hold, with no chance and no caveat, in ${language}`, () => {
      let drawn = 0;
      for (const member of members) {
        const container = card(language, {
          squad: member.squad,
          timing: { table: member.table, gains: member.gains },
          fixtures,
        });
        expect(container.querySelectorAll("[data-chip]").length, String(member.entryId)).toBe(
          member.rows,
        );
        const text = container.textContent ?? "";
        expect(text).not.toMatch(AS_A_CHANCE);
        expect(text).not.toMatch(AS_A_CAVEAT);
        if (member.rows > 0) drawn += 1;
        cleanup();
      }
      expect(drawn).toBeGreaterThan(0);
    });
  }
});
