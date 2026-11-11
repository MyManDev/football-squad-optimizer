import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { REPLAY_START_MS, REPLAY_STEP_MS } from "../../liveScore/liveReplay";
import { withLeague } from "../../../testSupport/league";
import type { ForwarderClient } from "../forwarder/client";
import { useGoalReplay } from "./useGoalReplay";
import type { MemberLiveDependencies } from "./useMemberLiveScore";

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
const LIVE = forwardedLive("finished", WEEK);
/** Two starters who played: the first scores twice, the second gives an assist. */
const [SCORER, PASSER] = LIVE.elements
  .filter((row) => MEMBER.pick_order.slice(0, 11).includes(row.element_id) && row.minutes > 0)
  .map((row) => row.element_id);
/** The reserve keeper, who played while the starting keeper did too: the scorer never counts them. */
const RESERVE = MEMBER.pick_order[11]!;

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  document.querySelectorAll("[data-opening-mark]").forEach((cover) => cover.remove());
});

function forwarder(moreGoals: Record<number, number> = {}) {
  const fixture = LIVE.fixtures[0]!;
  return {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(async () => ({
      ok: true,
      document: exampleBundle(ENTRY, WEEK, MEMBER),
      copy: "miss",
    })),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => ({ ok: false, reason: "network" })),
    liveActivity: vi.fn<NonNullable<ForwarderClient["liveActivity"]>>(async () => ({
      ok: true,
      copy: "miss",
      document: {
        contract_version: "week_activity_v1",
        week: LIVE,
        activity: {
          in_play_fixtures: [],
          appearances: LIVE.elements.map((row) => ({
            element_id: row.element_id,
            fixture_id: fixture.id,
            minutes: row.minutes,
            goals: row.element_id === SCORER ? 2 : (moreGoals[row.element_id] ?? 0),
            assists: row.element_id === PASSER ? 1 : 0,
          })),
        },
      },
    })),
  };
}

const loadTable: NonNullable<MemberLiveDependencies["loadTable"]> = async () => ({
  contract_version: "provisional_league_ui_v1",
  generated_at_utc: "2026-08-21T07:00:00Z",
  source_kind: "live",
  payload: TABLE,
});

function Harness({ client, enabled }: { client: ReturnType<typeof forwarder>; enabled: boolean }) {
  const batch = useGoalReplay(SQUAD, CALENDAR, { forwarder: client, loadTable }, enabled);
  return (
    <ul>
      {batch?.items.map((moment) => (
        <li key={moment.key}>
          {moment.kind === "substitution"
            ? `${batch.id}:substitution:${moment.out}>${moment.in}`
            : `${batch.id}:${moment.kind}:${moment.elementId}`}
        </li>
      ))}
    </ul>
  );
}

function show(client: ReturnType<typeof forwarder>, enabled = true) {
  return render(
    <LanguageProvider initialLanguage="tr">
      {withLeague(<Harness client={client} enabled={enabled} />)}
    </LanguageProvider>,
  );
}

const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("the GOL replay", () => {
  it("plays the week's goals and assists, then its automatic substitutions, a step apart, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const client = forwarder();
    show(client);
    await advance(0);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    await advance(REPLAY_START_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent(`1:goal:${SCORER}`);
    await advance(REPLAY_STEP_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent(`2:goal:${SCORER}`);
    await advance(REPLAY_STEP_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent(`3:assist:${PASSER}`);
    // The two starters who did not play go off for the first reserves who did, one board each.
    await advance(REPLAY_STEP_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent("4:substitution:Player 2>Player 14");
    await advance(REPLAY_STEP_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent("5:substitution:Player 7>Player 15");
    // Its last step over, the replay hands the board nothing more.
    await advance(REPLAY_STEP_MS * 3);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    // One read of the week, nothing more.
    expect(client.liveActivity).toHaveBeenCalledTimes(1);
    expect(client.entryBundle).toHaveBeenCalledTimes(1);
  });

  it("gives a reserve the scorer does not count no step of its own", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    show(forwarder({ [RESERVE]: 1 }));
    await advance(REPLAY_START_MS + REPLAY_STEP_MS * 3);
    expect(screen.getByRole("listitem")).toHaveTextContent("4:substitution:Player 2>Player 14");
  });

  it("reads nothing and plays nothing unless the address asks for it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const client = forwarder();
    show(client, false);
    await advance(REPLAY_START_MS + REPLAY_STEP_MS * 4);
    expect(screen.queryAllByRole("listitem")).toEqual([]);
    expect(client.entryBundle).not.toHaveBeenCalled();
  });

  it("waits for the opening cover to go", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const cover = document.createElement("div");
    cover.setAttribute("data-opening-mark", "");
    document.body.append(cover);
    const client = forwarder();
    show(client);
    await advance(REPLAY_START_MS + REPLAY_STEP_MS);
    expect(client.entryBundle).not.toHaveBeenCalled();
    await act(async () => {
      cover.remove();
    });
    await advance(REPLAY_START_MS);
    expect(screen.getByRole("listitem")).toHaveTextContent(`1:goal:${SCORER}`);
  });
});
