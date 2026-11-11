import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
import type { MemberWeek } from "../../liveScore/weekLive";
import { withLeague } from "../../../testSupport/league";
import type { ForwarderClient } from "../forwarder/client";
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
/** A starter who played and holds no armband: element 1, the goalkeeper. */
const SCORER = LIVE.elements.find(
  (row) => MEMBER.pick_order.includes(row.element_id) && row.minutes > 0,
)!.element_id;

let visibility: DocumentVisibilityState = "visible";
beforeEach(() => {
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

type ActivityAnswer = Awaited<ReturnType<NonNullable<ForwarderClient["liveActivity"]>>>;
type BundleAnswer = Awaited<ReturnType<ForwarderClient["entryBundle"]>>;

/** The scorer has played an hour, so the official scorer counts him and his armband. */
const activity = (goals: number, read: number, scorer: number): ActivityAnswer => {
  const elements = LIVE.elements.map((row) =>
    row.element_id === scorer && row.minutes === 0 ? { ...row, minutes: 60 } : row,
  );
  return {
    ok: true,
    copy: "miss",
    document: {
      contract_version: "week_activity_v1",
      week: {
        ...LIVE,
        elements,
        source_time: new Date(Date.parse(LIVE.source_time) + read * 60_000).toISOString(),
      },
      activity: {
        in_play_fixtures: [FIXTURE.id],
        appearances: elements.map((row) => ({
          element_id: row.element_id,
          fixture_id: FIXTURE.id,
          minutes: row.minutes,
          goals: row.element_id === scorer ? goals : 0,
          assists: 0,
        })),
      },
    },
  };
};

/**
 * The live week with the scorer's goals at each read, a minute apart; `null` is no answer.
 * `bundles` answers the bundle reads in turn, the last one again after that.
 */
function forwarder(
  goals: (number | null)[],
  {
    scorer = SCORER,
    member = MEMBER,
    bundles,
  }: { scorer?: number; member?: MemberWeek; bundles?: BundleAnswer[] } = {},
) {
  let read = 0;
  const answers: BundleAnswer[] = bundles ?? [
    { ok: true, document: exampleBundle(ENTRY, WEEK, member), copy: "miss" },
  ];
  let bundle = 0;
  return {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(
      async () => answers[Math.min(bundle++, answers.length - 1)]!,
    ),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => ({ ok: false, reason: "network" })),
    liveActivity: vi.fn(async (): Promise<ActivityAnswer> => {
      const count = goals[Math.min(read, goals.length - 1)]!;
      read += 1;
      if (count === null) return { ok: false, reason: "network" };
      return activity(count, read, scorer);
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
  follow: number | null;
}) {
  const live = useMemberLiveScore(SQUAD, CALENDAR, dependencies, true, follow);
  return (
    <div>
      <p data-testid="net">{live.shown ? String(live.shown.score.net) : "none"}</p>
      <p data-testid="batch">{live.moments ? String(live.moments.id) : "none"}</p>
      <p data-testid="refreshing">{String(live.refreshing)}</p>
      <button type="button" onClick={live.refresh}>
        refresh
      </button>
      <ul>
        {live.moments?.items.map((moment) => (
          <li key={moment.key}>{`${moment.kind}:${moment.elementId}:${moment.points}`}</li>
        ))}
      </ul>
    </div>
  );
}

const TABLES = new WeakMap<object, ReturnType<typeof loadTable>>();

function view(client: ReturnType<typeof forwarder>, follow: number | null) {
  // One table loader per client, so a rerender keeps the hook's dependencies.
  const table = TABLES.get(client) ?? loadTable();
  TABLES.set(client, table);
  return (
    <LanguageProvider initialLanguage="tr">
      {withLeague(
        <Harness dependencies={{ forwarder: client, loadTable: table }} follow={follow} />,
      )}
    </LanguageProvider>
  );
}

const shownNet = () =>
  screen.findByText(
    (_, element) =>
      element?.getAttribute("data-testid") === "net" && element.textContent !== "none",
  );

function follow(client: ReturnType<typeof forwarder>, following: number | null = WEEK) {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  return render(view(client, following));
}

const minute = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(FOLLOW_INTERVAL_MS);
  });

/** A goal's points for `element` in the example's season, times `armband`. */
function goalPoints(element: number, armband: number): string {
  const position = TABLE.players.find((player) => player.element_id === element)!.position;
  const values = SEASON_EVENT_POINTS[SQUAD.season];
  if (values === undefined) return "null";
  return String(values.goal[position as "GK" | "DEF" | "MID" | "FWD"] * armband);
}

describe("a followed live week", () => {
  it("reads the live points once a minute while in view, and names the goal a read brings", async () => {
    const client = forwarder([0, 1]);
    follow(client);
    await shownNet();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("batch")).toHaveTextContent("none");
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(`goal:${SCORER}:${goalPoints(SCORER, 1)}`)).toBeInTheDocument();
    // A later read asks for the live points alone.
    expect(client.entryBundle).toHaveBeenCalledTimes(1);
  });

  it("gives the captain's goal the scorer's armband, and three under the triple captain", async () => {
    const captain = MEMBER.captain;
    follow(forwarder([0, 1], { scorer: captain }));
    await shownNet();
    await minute();
    expect(
      await screen.findByText(`goal:${captain}:${goalPoints(captain, 2)}`),
    ).toBeInTheDocument();
    cleanup();
    follow(forwarder([0, 1], { scorer: captain, member: { ...MEMBER, active_chip: "3xc" } }));
    await shownNet();
    await minute();
    expect(
      await screen.findByText(`goal:${captain}:${goalPoints(captain, 3)}`),
    ).toBeInTheDocument();
  });

  it("never plays the same goal again", async () => {
    const client = forwarder([0, 1, 1, 1]);
    follow(client);
    await shownNet();
    await minute();
    await screen.findByText(`goal:${SCORER}:${goalPoints(SCORER, 1)}`);
    const batch = screen.getByTestId("batch").textContent;
    await minute();
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(4);
    expect(screen.getByTestId("batch")).toHaveTextContent(batch!);
  });

  it("reads nothing on its own while out of view, and once on coming back", async () => {
    const client = forwarder([0, 1]);
    follow(client);
    await shownNet();
    visibility = "hidden";
    await minute();
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(await screen.findByText(`goal:${SCORER}:${goalPoints(SCORER, 1)}`)).toBeInTheDocument();
  });

  it("keeps the shown week when a followed read is not answered", async () => {
    const client = forwarder([0, null]);
    follow(client);
    await shownNet();
    const net = screen.getByTestId("net").textContent;
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("net")).toHaveTextContent(net!);
  });

  it("makes the first read again at the next tick when it was not answered", async () => {
    const client = forwarder([0], {
      bundles: [
        { ok: false, reason: "network" },
        { ok: true, document: exampleBundle(ENTRY, WEEK, MEMBER), copy: "miss" },
      ],
    });
    follow(client);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("net")).toHaveTextContent("none");
    await minute();
    await shownNet();
    expect(client.entryBundle).toHaveBeenCalledTimes(2);
  });

  it("makes the first read again while the member's week is not the one being played", async () => {
    const client = forwarder([0, 0]);
    follow(client, WEEK + 1);
    await shownNet();
    await minute();
    expect(client.entryBundle).toHaveBeenCalledTimes(2);
  });

  it("leaves the member's refresh running when a followed read lands first", async () => {
    let release: (answer: ActivityAnswer) => void = () => undefined;
    const client = forwarder([0, 0]);
    const answer = client.liveActivity.getMockImplementation()!;
    client.liveActivity
      .mockImplementationOnce(answer)
      .mockImplementationOnce(() => new Promise<ActivityAnswer>((resolve) => (release = resolve)));
    follow(client);
    await shownNet();
    fireEvent.click(screen.getByRole("button", { name: "refresh" }));
    expect(screen.getByTestId("refreshing")).toHaveTextContent("true");
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("refreshing")).toHaveTextContent("true");
    await act(async () => {
      release(activity(0, 9, SCORER));
    });
    expect(screen.getByTestId("refreshing")).toHaveTextContent("false");
  });

  it("reads at once when a match starts with a read a minute old", async () => {
    const client = forwarder([0, 1]);
    const { rerender } = follow(client, null);
    await shownNet();
    await minute();
    await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    await act(async () => {
      rerender(view(client, WEEK));
    });
    expect(client.liveActivity).toHaveBeenCalledTimes(2);
  });

  it("reads nothing on its own while no match is being played", async () => {
    const client = forwarder([0, 1]);
    follow(client, null);
    await shownNet();
    for (let tick = 0; tick < 10; tick += 1) await minute();
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("batch")).toHaveTextContent("none");
  });
});
