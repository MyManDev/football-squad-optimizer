/**
 * The substitution board's motion on the member page (#1131): when a board first shows a
 * transfer pair the outgoing panel steps back and returns, the incoming one arrives, and
 * the gain comes up once they have finished; only transform and opacity move. It runs once
 * per change of the pair on a board's place, not on a re-render, and not at all under the
 * reduced-motion preference, where the board is in its end state at once.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MOTION_MS, REDUCED_MOTION_QUERY } from "../../../design/motion";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import type { AdviceMove, AdvicePlayer, EntryAdvice, LeagueViewEnvelope } from "../types";
import { BOARD_EASE, forgetPairs, GAIN, INCOMING, OUTGOING } from "./boardMotion";
import { LeagueMemberView } from "./LeagueMemberPage";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const EXAMPLE = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);

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

// A solved week with two moves, as the board test's own fixture.
const BASE: LeagueViewEnvelope<EntryAdvice> = {
  ...EXAMPLE,
  payload: {
    ...EXAMPLE.payload,
    moves: [
      move("gw-1", player(1, "Palmer"), player(2, "Fernandes"), 2.4),
      move("gw-2", player(3, "Jesus"), player(4, "Brobbey"), 0.6),
    ],
    expected_gain_vs_hold: 3,
    transfer_hit_points: 0,
    solver_status: "OPTIMAL",
    captain: player(5, "Haaland"),
    vice_captain: player(2, "Fernandes"),
  },
};
const COPY = MESSAGES.tr.leagueMembers;

interface Started {
  element: Element;
  keyframes: Keyframe[];
  options: KeyframeAnimationOptions;
}
let started: Started[] = [];
// What the recorded animations answer when asked whether they have finished.
let playState: AnimationPlayState = "running";

beforeEach(() => {
  forgetPairs();
  started = [];
  playState = "running";
  // jsdom has no Web Animations; this records each start and answers as a running one.
  Object.defineProperty(Element.prototype, "animate", {
    configurable: true,
    writable: true,
    value(this: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions) {
      started.push({ element: this, keyframes, options });
      return {
        get playState() {
          return playState;
        },
        cancel: vi.fn(),
      } as unknown as Animation;
    },
  });
});

afterEach(() => {
  cleanup();
  delete (Element.prototype as { animate?: unknown }).animate;
  delete (window as { matchMedia?: unknown }).matchMedia;
});

function reduceMotion() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      media: query,
      matches: query === REDUCED_MOTION_QUERY,
      addEventListener() {},
      removeEventListener() {},
    }),
  });
}

function withMoves(moves: AdviceMove[]): LeagueViewEnvelope<EntryAdvice> {
  return { ...BASE, payload: { ...BASE.payload, moves } };
}

function view(advice: LeagueViewEnvelope<EntryAdvice>) {
  return (
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
        {withLeague(
          <LeagueMemberView
            squad={SQUAD}
            advice={advice}
            members={mockLeagueMembersEnvelope.payload.members}
            index={mockEntryAdviceIndex(ENTRY).payload}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>
  );
}

const boards = () => screen.getAllByRole("article", { name: /^Değişiklik \d+\/\d+$/ });
const ANIMATED = new Set(["opacity", "transform", "offset"]);

describe("the substitution board's motion", () => {
  it("moves each board's players in the data time and brings the gain up after them", () => {
    const advice = BASE;
    render(view(advice));
    const count = advice.payload.moves.length;
    expect(count).toBeGreaterThan(0);
    expect(boards()).toHaveLength(count);
    expect(started).toHaveLength(count * 3);
    for (const board of boards()) {
      const mine = started.filter(({ element }) => board.contains(element));
      const [out, into, gain] = mine;
      expect(out!.keyframes).toBe(OUTGOING);
      expect(out!.element.className).toMatch(/out/);
      expect(into!.keyframes).toBe(INCOMING);
      expect(into!.element.className).toMatch(/in/);
      expect(gain!.keyframes).toBe(GAIN);
      expect(gain!.element.tagName).toBe("P");
      expect(out!.options).toEqual({ duration: MOTION_MS.data, easing: BOARD_EASE });
      expect(gain!.options.delay).toBe(MOTION_MS.data);
      expect(gain!.options.duration).toBe(MOTION_MS.ui);
    }
  });

  it("moves only transform and opacity", () => {
    for (const frame of [...OUTGOING, ...INCOMING, ...GAIN])
      for (const key of Object.keys(frame)) expect(ANIMATED.has(key)).toBe(true);
  });

  it("runs once per pair: not again on a re-render, again when the pair changes", () => {
    const moves = BASE.payload.moves;
    const { rerender } = render(view(withMoves(moves)));
    const first = started.length;
    expect(first).toBe(moves.length * 3);
    rerender(view(withMoves([...moves])));
    expect(started).toHaveLength(first);
    // The first board's incoming player changes; only that board moves again.
    const changed = {
      ...moves[0]!,
      player_in: { ...moves[0]!.player_in!, player_id: 999_001, name: "Yeni Oyuncu" },
    };
    rerender(view(withMoves([changed, ...moves.slice(1)])));
    expect(started).toHaveLength(first + 3);
    expect(boards()[0]!.contains(started[first]!.element)).toBe(true);
  });

  it("moves a board again when its pair comes back after a decision without that board", () => {
    const one = BASE.payload.moves[0]!;
    const { rerender } = render(view(withMoves([one])));
    expect(started).toHaveLength(3);
    playState = "finished";
    // A hold week: no board, so the place shows no pair.
    rerender(view(withMoves([])));
    expect(screen.queryAllByRole("article", { name: /^Değişiklik \d+\/\d+$/ })).toEqual([]);
    rerender(view(withMoves([one])));
    expect(started).toHaveLength(6);
  });

  it("moves the second board again when two moves come back after a plan with one", () => {
    const moves = BASE.payload.moves;
    const other = move("gw-3", player(6, "Saka"), player(7, "Gordon"), 1.1);
    const { rerender } = render(view(withMoves(moves)));
    expect(started).toHaveLength(6);
    playState = "finished";
    rerender(view(withMoves([other])));
    expect(started).toHaveLength(9);
    rerender(view(withMoves(moves)));
    expect(started).toHaveLength(15);
    expect(boards()[1]!.contains(started[14]!.element)).toBe(true);
  });

  it("does not move again when the same selection's boards mount again after their motion", () => {
    const first = render(view(BASE));
    const count = started.length;
    playState = "finished";
    first.unmount();
    render(view(BASE));
    expect(started).toHaveLength(count);
  });

  it("moves again when a remount stopped the motion before it finished", () => {
    const first = render(view(BASE));
    const count = started.length;
    first.unmount();
    render(view(BASE));
    expect(started).toHaveLength(count * 2);
  });

  it("does not move at all under reduced motion, and shows the board's end state at once", () => {
    reduceMotion();
    render(view(BASE));
    expect(started).toEqual([]);
    for (const board of boards()) {
      expect(board.querySelector("p")!.textContent).not.toBe("");
      expect(board.textContent).toContain(COPY.out);
      expect(board.textContent).toContain(COPY.in);
    }
  });

  it("shows the board without motion where the browser has no Web Animations", () => {
    delete (Element.prototype as { animate?: unknown }).animate;
    render(view(BASE));
    expect(boards().length).toBeGreaterThan(0);
  });
});
