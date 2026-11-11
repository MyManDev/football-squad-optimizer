import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { MemberLiveScore } from "./memberLiveScore";
import { useBoardHold, useBoardMoments, type BoardBatch } from "./useBoardMoments";
import type { MemberLive } from "./useMemberLiveScore";

afterEach(cleanup);

const NAMES = new Map([
  [4, "Saka"],
  [13, "Trossard"],
  [9, "Haaland"],
]);

/** A live week as the hook hands it on: only what the board reads of it. */
function live(minute: number, autosubs: [number, number][], moments: MemberLive["moments"] = null) {
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
});

function Holding({ batch, land }: { batch: BoardBatch | null; land?: string }) {
  const { held, landed } = useBoardHold(batch);
  return (
    <button type="button" onClick={() => land && landed(land)}>
      {held}
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

  it("holds a queued moment's points until its run lands, and nothing for a reserve", () => {
    const batch = { id: 1, items: [goal("a", 8, 2), goal("b", 4), goal("c", null, 0)] };
    const { rerender } = render(<Holding batch={batch} land="a" />);
    expect(screen.getByRole("button")).toHaveTextContent("12");
    screen.getByRole("button").click();
    rerender(<Holding batch={batch} land="b" />);
    expect(screen.getByRole("button")).toHaveTextContent("4");
    screen.getByRole("button").click();
    rerender(<Holding batch={batch} />);
    expect(screen.getByRole("button")).toHaveTextContent("0");
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
      const { held, waiting, landed } = useBoardHold(batch);
      return (
        <button type="button" onClick={() => landed(land)}>
          {`${held}:${waiting ? "waiting" : "clear"}`}
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
