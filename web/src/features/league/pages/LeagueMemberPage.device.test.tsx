/**
 * The device solve on the member page: offered where the publisher wrote the member's
 * inputs, the plan it proves shown as a computation result, one answer at a time with
 * the service, and nothing offered where the inputs are absent.
 */

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
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
import type { DevicePlanReply, DevicePlanRequest } from "../device/deviceSolver.worker";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DeviceSolver } from "../device/useDevicePlan";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import { exampleTree, withLeague } from "../../../testSupport/league";
import type { RequestOptions } from "../../../data/request";
import { StaticOnlyAdviceClient } from "../advice/adviceClient";

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
  /** Holding the fifteen instead: a plan that makes no transfer. */
  private readonly hold: boolean;
  constructor(hold = false) {
    this.hold = hold;
  }
  terminate(): void {}
  postMessage(request: DevicePlanRequest): void {
    const reply: DevicePlanReply = {
      id: request.id,
      kind: "answer",
      answer: {
        objective_scaled: 0,
        chip: null,
        objective: member.reference.objective_value,
        squad: member.reference.squad,
        starting_xi: member.reference.starting_xi,
        captain: member.reference.captain,
        vice_captain: member.reference.vice_captain,
        bench: member.reference.bench,
        transfers_in: this.hold ? [] : member.reference.transfers_in,
        transfers_out: this.hold ? [] : member.reference.transfers_out,
        transfer_hit_points: this.hold ? 0 : member.reference.transfer_hit_points,
        expected_own_points: member.reference.expected_own_points,
        hold_points: member.reference.hold_points,
        moves: this.hold ? [] : member.reference.moves,
        expected_gain_vs_hold: this.hold ? 0 : member.reference.expected_gain_vs_hold,
        seconds: 0.42,
      },
    };
    queueMicrotask(() => {
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>);
      this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
    });
  }
}

/** Moves the selection to a three-week window and back, through the URL as the page does. */
function SwitchWindow() {
  const [params, setParams] = useSearchParams();
  const to = (window: string) => {
    const next = new URLSearchParams(params);
    next.set("window", window);
    setParams(next);
  };
  return (
    <>
      <button type="button" onClick={() => to("3")}>
        to-3
      </button>
      <button type="button" onClick={() => to("1")}>
        to-1
      </button>
    </>
  );
}

class ServiceClient implements AdviceClient {
  async readAdvice(): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }
  /** The published baseline is the example tree's document, as the static client reads it. */
  readPublished(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult> {
    return new StaticOnlyAdviceClient(exampleTree.entryAdvice).readPublished(request, options);
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

function renderView(
  squad: LeagueViewEnvelope<EntrySquad>,
  search = "mode=saf-puan&window=1",
  hold = false,
) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?${search}`]}>
        <SwitchWindow />
        {withLeague(
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
              createSolver: () => new CannedSolver(hold),
              now: () => new Date("2026-10-03T01:02:03Z"),
            }}
          />,
        )}
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

  it("is dropped by a new selection and does not come back with the old one", async () => {
    const { container } = renderView(squadWith(entryBlock));
    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));
    await act(async () => screen.getByText("to-3").click());
    expect(container).not.toHaveTextContent(copy.deviceDone("0,4"));
    expect(deviceButton()).toBeNull();
    await act(async () => screen.getByText("to-1").click());
    expect(container).not.toHaveTextContent(copy.deviceDone("0,4"));
    expect(container).not.toHaveTextContent(copy.computeEcho(copy.computeEchoStates.device));
    expect(deviceButton()).not.toBeNull();
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

  it("says a device plan that holds the fifteen makes no transfer, without calling it published", async () => {
    const { container } = renderView(squadWith(entryBlock), "mode=saf-puan&window=1", true);
    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(container).toHaveTextContent(copy.deviceDone("0,4")));
    const decision = screen.getByRole("region", { name: copy.decisionTitle });
    expect(decision).toHaveTextContent(copy.noMove);
    expect(decision).not.toHaveTextContent(/yayımlanan plan|yayınlanan plan/i);
  });
});
