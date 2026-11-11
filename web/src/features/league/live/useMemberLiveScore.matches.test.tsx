import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { withLeague } from "../../../testSupport/league";
import type { ForwarderClient } from "../forwarder/client";
import { useMemberLiveScore, type MemberLiveDependencies } from "./useMemberLiveScore";

afterEach(cleanup);

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

function Harness({ dependencies }: { dependencies: MemberLiveDependencies }) {
  const live = useMemberLiveScore(SQUAD, CALENDAR, dependencies, true, null);
  const clubs = live.matches?.clubs;
  return <p data-testid="clubs">{clubs ? [...clubs].sort((a, b) => a - b).join(",") : "none"}</p>;
}

it("names the member's clubs from the scored week, as the forwarder sends no club", async () => {
  // The forwarder's own document: elements without positions or clubs.
  const week = forwardedLive("in_progress", WEEK);
  expect(week.elements.every((element) => element.club === undefined)).toBe(true);
  const forwarder = {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(async () => ({
      ok: true,
      document: exampleBundle(ENTRY, WEEK, MEMBER),
      copy: "miss",
    })),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => ({
      ok: true,
      document: week,
      copy: "miss",
    })),
  };
  const loadTable: NonNullable<MemberLiveDependencies["loadTable"]> = async () => ({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-08-21T07:00:00Z",
    source_kind: "live",
    payload: TABLE,
  });
  render(
    <LanguageProvider initialLanguage="tr">
      {withLeague(<Harness dependencies={{ forwarder, loadTable }} />)}
    </LanguageProvider>,
  );
  // The table names each pick's club; the calendar gives each club's team id.
  const ids = new Map(
    CALENDAR.gameweeks[0]!.fixtures.flatMap((fixture) => [
      [fixture.home.name, fixture.home.team_id] as const,
      [fixture.away.name, fixture.away.team_id] as const,
    ]),
  );
  const expected = [
    ...new Set(
      MEMBER.pick_order.map((id) => ids.get(TABLE.players.find((p) => p.element_id === id)!.team)!),
    ),
  ]
    .sort((a, b) => a - b)
    .join(",");
  expect(await screen.findByText(expected)).toBeInTheDocument();
});
