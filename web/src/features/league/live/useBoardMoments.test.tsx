import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { BoardMoment } from "../../liveScore/boardMoments";
import { GoalMomentLayer } from "../../liveScore/GoalMoment";
import { MOMENT_TIMING } from "../../liveScore/goalMomentTiming";
import type { MemberLiveScore } from "./memberLiveScore";
import { useBoardHold, useBoardMoments, useSettledRead, type BoardBatch } from "./useBoardMoments";
import type { MemberLive } from "./useMemberLiveScore";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const NAMES = new Map([
  [4, "Saka"],
  [13, "Trossard"],
  [9, "Haaland"],
]);

/** A live week as the hook hands it on: only what the board reads of it. */
function live(
  minute: number,
  autosubs: [number, number][],
  moments: MemberLive["moments"] = null,
  start = 1,
) {
  const shown = {
    gameweek: 11,
    names: NAMES,
    score: {
      source_time: new Date(Date.UTC(2026, 10, 21, 15, minute)).toISOString(),
      autosubs,
    },
  } as unknown as MemberLiveScore;
  return {
    shown,
    refreshing: false,
    refresh: () => undefined,
    moments,
    matches: null,
    start,
  } satisfies MemberLive;
}

function Harness({ value }: { value: MemberLive }) {
  const batch = useBoardMoments(value, 7);
  return (
    <ul>
      {batch?.items.map((item) => (
        <li key={item.key}>
          {batch.id}:{item.kind === "substitution" ? `${item.out}>${item.in}` : item.kind}
        </li>
      ))}
    </ul>
  );
}

describe("the GOL board's stream", () => {
  it("raises a substitution a newer read adds, once, after the first read's starting point", () => {
    const { rerender } = render(<Harness value={live(1, [[4, 13]])} />);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    rerender(<Harness value={live(2, [[4, 13]])} />);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    rerender(
      <Harness
        value={live(3, [
          [4, 13],
          [9, 13],
        ])}
      />,
    );
    expect(screen.getByRole("listitem")).toHaveTextContent("1:Haaland>Trossard");
    rerender(
      <Harness
        value={live(4, [
          [4, 13],
          [9, 13],
        ])}
      />,
    );
    expect(screen.getByRole("listitem")).toHaveTextContent("1:Haaland>Trossard");
  });

  it("carries a read's goals in the same stream, numbered after the substitutions", () => {
    const { rerender } = render(<Harness value={live(1, [])} />);
    const moments = {
      id: 1,
      items: [
        {
          key: "1:goal:9",
          kind: "goal" as const,
          size: "big" as const,
          elementId: 9,
          name: "Haaland",
          team: "Man City",
          position: "FWD" as const,
          count: 1,
          multiplier: 2 as const,
          base: 4,
          points: 8,
        },
      ],
    };
    rerender(<Harness value={live(2, [[4, 13]], moments)} />);
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "1:goal",
      "1:Saka>Trossard",
    ]);
  });

  it("takes the live score's new first read (a tool's page left) as a starting point", () => {
    const { rerender } = render(<Harness value={live(1, [])} />);
    // On a tool's page the live score shows no week; back on the page it reads afresh.
    rerender(<Harness value={{ ...live(2, []), shown: null }} />);
    rerender(<Harness value={live(3, [[4, 13]], null, 2)} />);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    // From there on a newer read's substitution rises as before.
    rerender(
      <Harness
        value={live(
          4,
          [
            [4, 13],
            [9, 13],
          ],
          null,
          2,
        )}
      />,
    );
    expect(screen.getByRole("listitem")).toHaveTextContent("1:Haaland>Trossard");
  });

  it("keeps counting over a refresh the source refused, as the live score keeps its goals", () => {
    const { rerender } = render(<Harness value={live(1, [])} />);
    // The member's refresh is refused: no week shown for a moment, but no new first read.
    rerender(<Harness value={{ ...live(2, []), shown: null }} />);
    rerender(<Harness value={live(3, [[4, 13]])} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("1:Saka>Trossard");
  });
});

function Holding({ batch, land }: { batch: BoardBatch | null; land?: string }) {
  const { brought, waiting, landed } = useBoardHold(batch);
  return (
    <button type="button" onClick={() => land && landed(land)}>
      {`${brought}:${waiting ? "waiting" : "clear"}`}
    </button>
  );
}

describe("the live score's hold", () => {
  const goal = (key: string, points: number | null, multiplier: 0 | 1 | 2 = 1) => ({
    key,
    kind: "goal" as const,
    size: "big" as const,
    elementId: 9,
    name: "Haaland",
    team: "Man City",
    position: "FWD" as const,
    count: 1,
    multiplier,
    base: points,
    points,
  });

  it("counts what the landed moments brought while it waits, and starts again once all have landed", () => {
    const batch = { id: 1, items: [goal("a", 8, 2), goal("b", 4), goal("c", null, 0)] };
    const { rerender } = render(<Holding batch={batch} land="a" />);
    // The reserve the scorer does not count is not waited for.
    expect(screen.getByRole("button")).toHaveTextContent("0:waiting");
    screen.getByRole("button").click();
    rerender(<Holding batch={batch} land="b" />);
    expect(screen.getByRole("button")).toHaveTextContent("8:waiting");
    screen.getByRole("button").click();
    rerender(<Holding batch={batch} />);
    // The last one landed: the page takes the newest read whole.
    expect(screen.getByRole("button")).toHaveTextContent("0:clear");
  });

  it("waits while a moment's points are on their way, and not once the last one lands", () => {
    const batch = { id: 1, items: [goal("a", 5), goal("b", 3)] };
    function Waiting({ land }: { land: string }) {
      const { waiting, landed } = useBoardHold(batch);
      return (
        <button type="button" onClick={() => landed(land)}>
          {waiting ? "waiting" : "clear"}
        </button>
      );
    }
    const { rerender } = render(<Waiting land="a" />);
    expect(screen.getByRole("button")).toHaveTextContent("waiting");
    screen.getByRole("button").click();
    rerender(<Waiting land="b" />);
    expect(screen.getByRole("button")).toHaveTextContent("waiting");
    screen.getByRole("button").click();
    rerender(<Waiting land="b" />);
    expect(screen.getByRole("button")).toHaveTextContent("clear");
  });

  it("waits for a substitution's board and a card's line too, holding no points for them", () => {
    const card = { ...goal("card", null), kind: "card" as const, size: "small" as const };
    const swap = {
      key: "swap",
      kind: "substitution" as const,
      size: "big" as const,
      out: "Rogers",
      in: "Cherki",
    };
    const batch = { id: 1, items: [swap, card] };
    function Waiting({ land }: { land: string }) {
      const { brought, waiting, landed } = useBoardHold(batch);
      return (
        <button type="button" onClick={() => landed(land)}>
          {`${brought}:${waiting ? "waiting" : "clear"}`}
        </button>
      );
    }
    const { rerender } = render(<Waiting land="swap" />);
    expect(screen.getByRole("button")).toHaveTextContent("0:waiting");
    screen.getByRole("button").click();
    rerender(<Waiting land="card" />);
    expect(screen.getByRole("button")).toHaveTextContent("0:waiting");
    screen.getByRole("button").click();
    rerender(<Waiting land="card" />);
    expect(screen.getByRole("button")).toHaveTextContent("0:clear");
  });
});

describe("the hold played out by the GOL layer", () => {
  const counted = (key: string, points: number, size: "big" | "small" = "big"): BoardMoment => ({
    key,
    kind: "goal",
    size,
    elementId: 9,
    name: "Haaland",
    team: "Man City",
    position: "FWD",
    count: 1,
    multiplier: 1,
    base: points,
    points,
  });
  const SWAP: BoardMoment = {
    key: "swap",
    kind: "substitution",
    size: "big",
    out: "Rogers",
    in: "Cherki",
  };
  function Page({ batch }: { batch: BoardBatch }) {
    const hold = useBoardHold(batch);
    return (
      <LanguageProvider initialLanguage="tr">
        <GoalMomentLayer
          batch={{ id: `live:${batch.id}`, items: batch.items }}
          onLanded={hold.landed}
        />
        <output data-testid="hold">{`${hold.brought}:${hold.waiting ? "waiting" : "clear"}`}</output>
      </LanguageProvider>
    );
  }
  const hold = () => screen.getByTestId("hold");
  const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));
  const board = MOMENT_TIMING.rise + MOMENT_TIMING.holdGoal;

  it("lets go of a read's four counted goals once the three boards and the fourth's line have gone", () => {
    vi.useFakeTimers();
    // A read's fourth counted moment plays as a small line (liveMoments keeps three boards).
    const batch = {
      id: 1,
      items: [counted("a", 4), counted("b", 4), counted("c", 4), counted("d", 4, "small")],
    };
    render(<Page batch={batch} />);
    expect(hold()).toHaveTextContent("0:waiting");
    advance(board);
    advance(board);
    advance(board);
    // Three goals of 4 have landed; the fourth's line still stands.
    expect(hold()).toHaveTextContent("12:waiting");
    advance(MOMENT_TIMING.line);
    expect(hold()).toHaveTextContent("0:clear");
  });

  it("waits while a substitution's board stands, and not once it has gone", () => {
    vi.useFakeTimers();
    render(<Page batch={{ id: 1, items: [SWAP] }} />);
    expect(hold()).toHaveTextContent("0:waiting");
    advance(MOMENT_TIMING.rise + MOMENT_TIMING.holdAssist);
    expect(hold()).toHaveTextContent("0:clear");
  });

  it("holds nothing once reduced motion is turned on and the next read comes as a still line", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <Page batch={{ id: 1, items: [counted("a", 4), counted("b", 5)] }} />,
    );
    expect(hold()).toHaveTextContent("0:waiting");
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    rerender(<Page batch={{ id: 2, items: [counted("c", 6)] }} />);
    expect(hold()).toHaveTextContent("0:clear");
    expect(document.querySelector("[data-goal-still]")).not.toBeNull();
  });
});

describe("the read a page draws", () => {
  function Drawn({
    read,
    waiting,
  }: {
    read: { gameweek: number; at: string } | null;
    waiting: boolean;
  }) {
    const drawn = useSettledRead(read, waiting);
    return <p>{drawn === null ? "none" : drawn.at}</p>;
  }

  it("is the read from before the board's first moment while it waits, then the newest", () => {
    const { rerender } = render(<Drawn read={{ gameweek: 11, at: "15:40" }} waiting={false} />);
    // A read brings a moment: the page keeps drawing the one before until it has landed.
    rerender(<Drawn read={{ gameweek: 11, at: "15:41" }} waiting />);
    expect(screen.getByText("15:40")).toBeInTheDocument();
    rerender(<Drawn read={{ gameweek: 11, at: "15:42" }} waiting />);
    expect(screen.getByText("15:40")).toBeInTheDocument();
    rerender(<Drawn read={{ gameweek: 11, at: "15:42" }} waiting={false} />);
    expect(screen.getByText("15:42")).toBeInTheDocument();
  });

  it("never draws another week's read for this one", () => {
    const { rerender } = render(<Drawn read={{ gameweek: 10, at: "10" }} waiting={false} />);
    rerender(<Drawn read={{ gameweek: 11, at: "11" }} waiting />);
    expect(screen.getByText("11")).toBeInTheDocument();
  });
});
