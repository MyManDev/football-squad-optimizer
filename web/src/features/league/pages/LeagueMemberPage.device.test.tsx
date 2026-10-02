/**
 * The device solve on the member page: offered where the publisher wrote the member's
 * inputs, the plan it proves shown as a computation result, one answer at a time with
 * the service, and nothing offered where the inputs are absent.
 */

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestResult,
} from "../advice/adviceClient";
import type { DevicePlanReply, DevicePlanRequest } from "../device/devicePlan.worker";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DeviceSolver } from "../device/useDevicePlan";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const INDEX = mockEntryAdviceIndex(ENTRY).payload;
const copy = MESSAGES.tr.leagueMembers;
const PLAN_SHOWN = copy.squadAfterTitle;
const document = fixture.document as unknown as DevicePlanDocument;
const member = fixture.members[2]!;
const entryBlock = member.entry as unknown as DevicePlanEntry;

function squadWith(block: DevicePlanEntry | null): LeagueViewEnvelope<EntrySquad> {
  const base = mockEntrySquadEnvelopes[ENTRY]!;
  return {
    ...base,
    payload: {
      ...base.payload,
      source_snapshot_id: document.source_snapshot_id,
      device_plan: block,
    },
  };
}

/** The real model, answered in process without a worker thread. */
class CannedSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  terminate(): void {}
  postMessage(request: DevicePlanRequest): void {
    const reply: DevicePlanReply = {
      id: request.id,
      kind: "answer",
      answer: {
        objective_scaled: 0,
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
    queueMicrotask(() => this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>));
  }
}

class ServiceClient implements AdviceClient {
  async readAdvice(): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }
  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    return {
      kind: "advice",
      envelope: mockEntryAdviceEnvelope(request.entryId, request.strategy, request.window),
      source: "api-cache",
    };
  }
  async readJob(jobId: string): Promise<AdviceJobStatus> {
    return { jobId, status: "completed" };
  }
}

function renderView(squad: LeagueViewEnvelope<EntrySquad>, search = "mode=saf-puan&window=1") {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${search}`]}>
        <LeagueMemberView
          squad={squad}
          advice={null}
          adviceIssue="not-listed"
          members={MEMBERS}
          index={INDEX}
          client={new ServiceClient()}
          deviceDependencies={{
            loadDocument: async () => ({
              contract_version: "provisional_league_ui_v1",
              generated_at_utc: "2026-10-03T00:00:00Z",
              source_kind: "live",
              payload: document,
            }),
            createSolver: () => new CannedSolver(),
            now: () => new Date("2026-10-03T01:02:03Z"),
          }}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

const deviceButton = () => screen.queryByRole("button", { name: copy.deviceButton });

describe("the device solve on the member page", () => {
  it("is offered where the publisher wrote the member's inputs, and nowhere else", () => {
    renderView(squadWith(entryBlock));
    expect(deviceButton()).not.toBeNull();
    cleanup();
    renderView(squadWith(null));
    expect(deviceButton()).toBeNull();
    cleanup();
    renderView(squadWith(entryBlock), "mode=saf-puan&window=3");
    expect(deviceButton()).toBeNull();
  });

  it("shows the plan the device proved as a computation result, with its time", async () => {
    const { container } = renderView(squadWith(entryBlock));
    expect(screen.queryByText(PLAN_SHOWN)).toBeNull();
    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(screen.getByText(PLAN_SHOWN)).toBeVisible());
    expect(container).toHaveTextContent(copy.deviceDone("0,4"));
    expect(container).toHaveTextContent(copy.adviceComputedBadge);
    expect(container).toHaveTextContent(copy.computeEcho(copy.computeEchoStates.device));
    expect(container).toHaveTextContent(copy.stampOptimal);
    // The transfers the reference names, by the names the document gives them.
    const names = new Map(document.players.map((p) => [p.id, p.name]));
    for (const move of member.reference.moves) {
      expect(container).toHaveTextContent(names.get(move.in!)!);
    }
    expect(container).not.toHaveTextContent("%");
  });

  it("gives way to the service's answer, and takes the page back when asked again", async () => {
    const { container } = renderView(squadWith(entryBlock));
    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));

    await act(async () => screen.getByRole("button", { name: "Hesapla" }).click());
    await waitFor(() => expect(container).toHaveTextContent(copy.computeDone));
    expect(container).not.toHaveTextContent(copy.deviceDone("0,4"));
    expect(container).toHaveTextContent(copy.computeEcho(copy.computeEchoStates.done));

    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));
    expect(container).toHaveTextContent(copy.computeEcho(copy.computeEchoStates.device));
  });
});
