/**
 * The chip timing card on the member page (#1003): read from the device's run of the plain
 * one-week plan, beside the chip control, in a league whose tree publishes no advice index.
 * Nothing is drawn before the device has run, nor where the reading is refused.
 */

import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import type { Fixture, FixturesPayload } from "../../fixtures/types";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import type { DevicePlanReply, DevicePlanRequest } from "../device/deviceSolver.worker";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DeviceSolver } from "../device/useDevicePlan";
import type { EntrySquad, EntrySquadPlayer, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const copy = MESSAGES.tr.leagueMembers;
const document = fixture.document as unknown as DevicePlanDocument;
const member = fixture.members[2]!;
const entryBlock = member.entry as unknown as DevicePlanEntry;
const players = new Map(document.players.map((player) => [player.id, player]));
const CLUBS = [...new Set(document.players.map((player) => player.team))].sort();

/** The member's own fifteen from the device block, at the table's capture and gameweek. */
function squad(): LeagueViewEnvelope<EntrySquad> {
  const base = mockEntrySquadEnvelopes[ENTRY]!;
  const held = entryBlock.held;
  const player = (id: number): EntrySquadPlayer => ({
    ...base.payload.starting_xi[0]!,
    player_id: id,
    name: players.get(id)!.name,
    short_name: players.get(id)!.short_name,
    team: players.get(id)!.team,
    is_captain: id === held[1],
    is_vice_captain: false,
  });
  return {
    ...base,
    payload: {
      ...base.payload,
      gameweek: document.gameweek,
      source_snapshot_id: document.source_snapshot_id,
      device_plan: entryBlock,
      starting_xi: held.slice(0, 11).map(player),
      bench: held.slice(11).map(player),
      chips: { ...base.payload.chips!, gameweek: document.gameweek },
    },
  };
}

/** Each club of the table once a week, all season, under the table's capture. */
function calendar(): FixturesPayload {
  const team = (index: number) => ({
    team_id: index + 1,
    name: CLUBS[index]!,
    short_name: `C${index + 1}`,
  });
  return {
    season: document.season,
    source_snapshot_id: document.source_snapshot_id,
    captured_at_utc: "2026-10-03T00:00:00Z",
    current_gameweek: document.gameweek,
    unscheduled_count: 0,
    gameweeks: Array.from({ length: 38 }, (_, index) => ({
      gameweek: index + 1,
      deadline_utc: "2999-01-01T00:00:00Z",
      fixtures: Array.from({ length: CLUBS.length / 2 }, (_, pair): Fixture => ({
        fixture_id: (index + 1) * 100 + pair,
        kickoff_utc: null,
        home: team(pair * 2),
        away: team(pair * 2 + 1),
        finished: false,
        home_score: null,
        away_score: null,
      })),
    })),
  };
}

/**
 * The worker's two replies for chip gains: the plain plan as the reference states it, at
 * once, then the gains the request asked for when the test releases them. Wildcard and
 * Free Hit far above their thresholds, Bench Boost refused (unknown) and Triple Captain
 * at nothing. It keeps every request posted to it.
 */
class ChipGainsSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  readonly posted: DevicePlanRequest[] = [];
  terminate(): void {}
  postMessage(request: DevicePlanRequest): void {
    this.posted.push(request);
    const plan: DevicePlanReply = {
      id: request.id,
      kind: request.chipGains ? "plan" : "answer",
      answer: {
        objective_scaled: 0,
        chip: null,
        objective: member.reference.objective_value,
        squad: member.reference.squad,
        starting_xi: member.reference.starting_xi,
        captain: member.reference.captain,
        vice_captain: member.reference.vice_captain,
        bench: member.reference.bench,
        transfers_in: member.reference.transfers_in,
        transfers_out: member.reference.transfers_out,
        transfer_hit_points: member.reference.transfer_hit_points,
        expected_own_points: member.reference.expected_own_points,
        hold_points: member.reference.hold_points,
        moves: member.reference.moves,
        expected_gain_vs_hold: member.reference.expected_gain_vs_hold,
        seconds: 0.42,
      },
    };
    queueMicrotask(() => {
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>);
      this.onmessage?.({ data: plan } as MessageEvent<DevicePlanReply>);
    });
  }
  /** The gains of the last request, as the worker posts them after the plan. */
  release(): void {
    const request = this.posted.at(-1)!;
    const gains = { wildcard: 30, freehit: 30, bboost: null, "3xc": 0 };
    this.onmessage?.({
      data: {
        id: request.id,
        kind: "gains",
        gains: Object.fromEntries(request.chipGains!.map((chip) => [chip, gains[chip]])),
        seconds: 3.2,
      },
    } as MessageEvent<DevicePlanReply>);
  }
}

function renderView(solver: DeviceSolver, fixtures: FixturesPayload | null = calendar()) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?mode=saf-puan&window=1`]}>
        {withLeague(
          <LeagueMemberView
            squad={squad()}
            advice={null}
            // A tree with no advice index: the device is the page's only plan.
            adviceIssue="index-missing"
            members={mockLeagueMembersEnvelope.payload.members}
            index={null}
            fixtures={fixtures}
            deviceDependencies={{
              loadDocument: async () => ({
                contract_version: "provisional_league_ui_v1",
                generated_at_utc: "2026-10-03T00:00:00Z",
                source_kind: "live",
                payload: document,
              }),
              createSolver: () => solver,
              now: () => new Date("2026-10-03T01:02:03Z"),
            }}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const deviceButton = () => screen.getByRole("button", { name: copy.deviceButton });

describe("the chip timing card on the member page", () => {
  it("appears beside the chip control once the device has solved the plain plan", async () => {
    const solver = new ChipGainsSolver();
    const { container } = renderView(solver);
    expect(container.querySelector("[data-chip-timing]")).toBeNull();
    await act(async () => deviceButton().click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));
    // The held chips, in the game's order, each solved once beside the plain plan.
    expect(solver.posted.map((request) => request.chipGains)).toEqual([
      ["wildcard", "freehit", "bboost", "3xc"],
    ]);
    // The plan is on the page before the gains; the card waits for them.
    expect(container.querySelector("[data-chip-timing]")).toBeNull();
    await act(async () => solver.release());
    // The timing line still counts the plain plan's solve only.
    expect(container).toHaveTextContent(copy.deviceDone("0,4"));
    const card = container.querySelector<HTMLElement>("[data-chip-timing]")!;
    expect(card).not.toBeNull();
    // In the same settings tool as the chip control, right after it.
    const tool = card.closest("details")!;
    expect(within(tool).getByRole("group", { name: "Çip" })).toBeInTheDocument();
    expect(within(card).getByRole("heading", { name: "Çip zamanı" })).toBeInTheDocument();
    const rows = [...card.querySelectorAll("[data-chip]")].map((row) => [
      row.getAttribute("data-chip"),
      row.querySelector("dd")!.textContent,
    ]);
    // Bench Boost's solve was refused: its gain is unknown and it has no row.
    expect(rows.map(([name]) => name)).toEqual(["wildcard", "freehit", "3xc"]);
    expect(rows[0]![1]).toBe("Bu hafta, +30,0 xP beklenen puan");
    expect(rows[1]![1]).toBe("Bu hafta değil, 19. haftaya kadar");
  });

  it("draws nothing where the reading is refused", async () => {
    const solver = new ChipGainsSolver();
    const { container } = renderView(solver, null);
    await act(async () => deviceButton().click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));
    await act(async () => solver.release());
    expect(container.querySelector("[data-chip-timing]")).toBeNull();
    expect(container).not.toHaveTextContent("Çip zamanı");
  });
});
