import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { MemberLiveScore } from "./memberLiveScore";
import { useBoardMoments } from "./useBoardMoments";
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
