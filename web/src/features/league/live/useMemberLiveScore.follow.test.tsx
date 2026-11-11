import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { SEASON_EVENT_POINTS } from "../../liveScore/liveMoments";
import { FOLLOW_INTERVAL_MS } from "../../liveScore/liveWindow";
import { withLeague } from "../../../testSupport/league";
import type { ForwarderClient } from "../forwarder/client";
import { memberLiveScore } from "./memberLiveScore";
import { useMemberLiveScore, type MemberLiveDependencies } from "./useMemberLiveScore";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!.payload;
const WEEK = SQUAD.gameweek;
const CALENDAR = exampleCalendar({
  season: SQUAD.season,
  gameweek: WEEK,
  deadline: "2026-08-21T17:30:00Z",
});
const TABLE = exampleTable({
  season: SQUAD.season,
  gameweek: WEEK,
  capture: SQUAD.source_snapshot_id!,
});
const MEMBER = exampleMember(ENTRY, WEEK);
const LIVE = forwardedLive("in_progress", WEEK);
const FIXTURE = LIVE.fixtures.find((row) => !row.finished)!;
const SCORER = LIVE.elements.find(
  (row) => MEMBER.pick_order.includes(row.element_id) && row.minutes > 0,
)!;

let visibility: DocumentVisibilityState = "visible";
beforeEach(() => {
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

type ActivityAnswer = Awaited<ReturnType<NonNullable<ForwarderClient["liveActivity"]>>>;

/** The live week with the scorer's goals at each read, a minute apart; `null` is no answer. */
function forwarder(goals: (number | null)[]) {
  let read = 0;
  return {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(async () => ({
      ok: true,
      document: exampleBundle(ENTRY, WEEK, MEMBER),
      copy: "miss",
    })),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => ({ ok: false, reason: "network" })),
    liveActivity: vi.fn(async (): Promise<ActivityAnswer> => {
      const count = goals[Math.min(read, goals.length - 1)]!;
      read += 1;
      if (count === null) return { ok: false, reason: "network" };
      return {
        ok: true,
        copy: "miss",
        document: {
          contract_version: "week_activity_v1",
          week: {
            ...LIVE,
            source_time: new Date(Date.parse(LIVE.source_time) + read * 60_000).toISOString(),
          },
          activity: {
            in_play_fixtures: [FIXTURE.id],
            appearances: LIVE.elements.map((row) => ({
              element_id: row.element_id,
              fixture_id: FIXTURE.id,
              minutes: row.minutes,
              goals: row.element_id === SCORER.element_id ? count : 0,
              assists: 0,
            })),
          },
        },
      };
    }),
  };
}

const loadTable = () =>
  vi.fn<NonNullable<MemberLiveDependencies["loadTable"]>>(async () => ({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-08-21T07:00:00Z",
    source_kind: "live",
    payload: TABLE,
  }));

function Harness({
  dependencies,
  follow,
}: {
  dependencies: MemberLiveDependencies;
  follow: boolean;
}) {
  const live = useMemberLiveScore(SQUAD, CALENDAR, dependencies, true, follow);
  return (
    <div>
      <p data-testid="net">{live.shown ? String(live.shown.score.net) : "none"}</p>
      <p data-testid="batch">{live.moments ? String(live.moments.id) : "none"}</p>
      <ul>
        {live.moments?.items.map((moment) => (
          <li key={moment.key}>{`${moment.kind}:${moment.elementId}:${moment.points}`}</li>
        ))}
      </ul>
    </div>
  );
}

async function follow(goals: (number | null)[], following = true) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const client = forwarder(goals);
  render(
    <LanguageProvider initialLanguage="tr">
      {withLeague(
        <Harness dependencies={{ forwarder: client, loadTable: loadTable() }} follow={following} />,
      )}
    </LanguageProvider>,
  );
  await screen.findByText(
    (_, element) =>
      element?.getAttribute("data-testid") === "net" && element.textContent !== "none",
  );
  return client;
}

const minute = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FOLLOW_INTERVAL_MS);
  });

/** The points a goal by the scorer brings this member, from the season and the scorer's verdict. */
function goalPoints(): string {
  const scored = memberLiveScore({ live: LIVE, member: MEMBER, table: TABLE, fixtures: CALENDAR });
  if (!scored.ok) throw new Error(scored.reason);
  const position = TABLE.players.find(
    (player) => player.element_id === SCORER.element_id,
  )!.position;
  const values = SEASON_EVENT_POINTS[SQUAD.season];
  if (values === undefined) return "null";
  const counted = scored.live.score.counted.includes(SCORER.element_id);
  const armband =
    scored.live.score.captain === SCORER.element_id ? (MEMBER.active_chip === "3xc" ? 3 : 2) : 1;
  return String(values.goal[position as "GK" | "DEF" | "MID" | "FWD"] * (counted ? armband : 0));
}

describe("a followed live week", () => {
  it("reads the live points once a minute while in view, and names the goal a read brings", async () => {
    const client = await follow([0, 1]);
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("batch")).toHaveTextContent("none");
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(
      await screen.findByText(`goal:${SCORER.element_id}:${goalPoints()}`),
    ).toBeInTheDocument();
    // A later read asks for the live points alone.
    expect(client.entryBundle).toHaveBeenCalledTimes(1);
  });

  it("never plays the same goal again", async () => {
    const client = await follow([0, 1, 1, 1]);
    await minute();
    await screen.findByText(`goal:${SCORER.element_id}:${goalPoints()}`);
    const batch = screen.getByTestId("batch").textContent;
    await minute();
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(4);
    expect(screen.getByTestId("batch")).toHaveTextContent(batch!);
  });

  it("reads nothing on its own while out of view, and once on coming back", async () => {
    const client = await follow([0, 1]);
    visibility = "hidden";
    await minute();
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(
      await screen.findByText(`goal:${SCORER.element_id}:${goalPoints()}`),
    ).toBeInTheDocument();
  });

  it("keeps the shown week when a followed read is not answered", async () => {
    const client = await follow([0, null]);
    const net = screen.getByTestId("net").textContent;
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("net")).toHaveTextContent(net!);
  });

  it("reads nothing on its own while no match is being played", async () => {
    const client = await follow([0, 1], false);
    for (let tick = 0; tick < 10; tick += 1) await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("batch")).toHaveTextContent("none");
  });
});
