/**
 * The one-week plan solved when the member page opens (#981 step 4, answers 4 and 5 (a) of
 * 6165942058): only where the member's index publishes no one-week plan (a device menu) and
 * only while the week's deadline is known and ahead, on the decision's page and on a tool
 * page's address alike. Where a plan is published the button stays as it was. One run at a
 * time: a remount of the page's effects, a late read, a visit to a tool page or a member
 * who asks the service starts no second run and ends none; a new selection ends the run
 * and the page solves the new one.
 */

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
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
import { withLeague } from "../../../testSupport/league";
import type { MemberTool } from "../../../lib/leagueAddresses";
import type { FixturesPayload } from "../../fixtures/types";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestResult,
} from "../advice/adviceClient";
import type { DevicePlanReply, DevicePlanRequest } from "../device/deviceSolver.worker";
import type { DevicePlanDocument, DevicePlanEntry } from "../device/types";
import type { DevicePlanDependencies, DeviceSolver } from "../device/useDevicePlan";
import type { EntryAdviceIndex, EntrySquad, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { solvesOnOpen } from "./memberSelection";

afterEach(cleanup);

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const copy = MESSAGES.tr.leagueMembers;
const PLAN_SHOWN = copy.squadAfterTitle;
const DONE = copy.deviceDone("0,4");
const document = fixture.document as unknown as DevicePlanDocument;
const member = fixture.members[2]!;

const SQUAD: LeagueViewEnvelope<EntrySquad> = (() => {
  const base = mockEntrySquadEnvelopes[ENTRY]!;
  return {
    ...base,
    payload: {
      ...base.payload,
      source_snapshot_id: document.source_snapshot_id,
      device_plan: member.entry as unknown as DevicePlanEntry,
    },
  };
})();
const view = SQUAD.payload;

/** The full menu as 352490 publishes it today: the one-week plans are on the tree. */
const PUBLISHED_INDEX: EntryAdviceIndex = { ...mockEntryAdviceIndex(ENTRY).payload, menu: "full" };
/** A device menu: the inputs are published and no plan is. */
const DEVICE_INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  menu: "device",
  source_snapshot_id: document.source_snapshot_id,
  windows: { "saf-puan": [], "ortak-koru": [], "fark-yarat": [] },
  computed: [],
  unavailable: [],
  chip_states: { known: false, gameweek: view.gameweek, states: {} },
  chips: { available: false, reason: "on_device" },
  top100: { available: false, reason: "on_device" },
  evidence: { available: false, reason: "on_device" },
};

function calendar(deadline: string): FixturesPayload {
  return {
    season: view.season,
    source_snapshot_id: "fixtures-capture",
    captured_at_utc: "2026-10-03T00:00:00Z",
    current_gameweek: view.gameweek,
    unscheduled_count: 0,
    gameweeks: [{ gameweek: view.gameweek, deadline_utc: deadline, fixtures: [] }],
  };
}
const OPEN_WEEK = calendar("2999-01-01T00:00:00Z");
/** A compute service on this capture that answers the plain one-week plan. */
const SERVICE: AdviceCapabilities = {
  leagueId: view.league_id,
  captureSnapshotId: document.source_snapshot_id,
  season: view.season,
  gameweek: view.gameweek,
  strategies: { "saf-puan": { windows: [1], requiresRival: false } },
  top100Weights: [0],
  managersWord: false,
};
const CLOSED_WEEK = calendar("2020-01-01T00:00:00Z");

/** The real model's answer, in process without a worker thread. */
class CannedSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
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
      this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
    });
  }
}

/** A worker that loads and never answers: its solve is still running while the page changes. */
class StillSolving implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  terminated = false;
  postMessage(request: DevicePlanRequest): void {
    queueMicrotask(() =>
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>),
    );
  }
  terminate(): void {
    this.terminated = true;
  }
}

/** A service that has nothing cached and answers a request with the example plan. */
class ServiceClient implements AdviceClient {
  async readAdvice(): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }
  async readPublished(): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }
  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    const envelope = mockEntryAdviceEnvelope(request.entryId, request.strategy, request.window);
    return {
      kind: "advice",
      envelope: {
        ...envelope,
        payload: { ...envelope.payload, source_snapshot_id: document.source_snapshot_id },
      },
      source: "api-cache",
    };
  }
  async readJob(jobId: string): Promise<AdviceJobStatus> {
    return { jobId, status: "completed" };
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

/** What changes between renders: the page's reads, its week and the tool its address names. */
type Shown = Partial<
  Pick<
    LeagueMemberViewProps,
    | "index"
    | "advice"
    | "adviceIssue"
    | "adviceLoading"
    | "deadlinePassed"
    | "fixtures"
    | "tool"
    | "capabilities"
    | "computeService"
  >
>;

const DEVICE_MENU: Shown = {
  index: DEVICE_INDEX,
  advice: null,
  adviceIssue: "not-listed",
  adviceLoading: false,
  deadlinePassed: null,
  fixtures: OPEN_WEEK,
};

/** The member page, its device solving in the workers it creates and counting the posts. */
function memberPage(createSolver: () => DeviceSolver, strict = false) {
  const posted: DevicePlanRequest[] = [];
  const counted = () => {
    const solver = createSolver();
    const post = solver.postMessage.bind(solver);
    solver.postMessage = (request) => {
      posted.push(request);
      post(request);
    };
    return solver;
  };
  const client = new ServiceClient();
  const deviceDependencies: DevicePlanDependencies = {
    loadDocument: async () => ({
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: "2026-10-03T00:00:00Z",
      source_kind: "live",
      payload: document,
    }),
    createSolver: counted,
    now: () => new Date("2026-10-03T01:02:03Z"),
  };
  const page = (shown: Shown) => {
    const tool: MemberTool | undefined = shown.tool;
    const address = `/league/352490/members/${ENTRY}${tool ? `/${tool}` : ""}`;
    const tree: ReactNode = (
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`${address}?mode=saf-puan&window=1`]}>
          <SwitchWindow />
          {withLeague(
            <LeagueMemberView
              squad={SQUAD}
              members={MEMBERS}
              client={client}
              deviceDependencies={deviceDependencies}
              advice={null}
              {...shown}
            />,
          )}
        </MemoryRouter>
      </LanguageProvider>
    );
    return strict ? <StrictMode>{tree}</StrictMode> : tree;
  };
  return { page, posted };
}

const deviceButton = () => screen.queryByRole("button", { name: copy.deviceButton });
const deviceState = (container: HTMLElement) =>
  container.querySelector("[data-device-state]")?.getAttribute("data-device-state") ?? null;

describe("the rule for solving on opening", () => {
  it("holds only for a device menu in a week whose deadline is known and ahead", () => {
    expect(solvesOnOpen(DEVICE_INDEX, true)).toBe(true);
    expect(solvesOnOpen(DEVICE_INDEX, false)).toBe(false);
    expect(solvesOnOpen(PUBLISHED_INDEX, true)).toBe(false);
    expect(solvesOnOpen({ ...PUBLISHED_INDEX, menu: undefined }, true)).toBe(false);
    expect(solvesOnOpen(null, true)).toBe(false);
  });
});

describe("the member page with no published one-week plan", () => {
  it("solves the plan on opening, before the deadline, with no press", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container } = render(page(DEVICE_MENU));
    await waitFor(() => expect(screen.getByText(PLAN_SHOWN)).toBeVisible());
    expect(container).toHaveTextContent(DONE);
    expect(container).toHaveTextContent(copy.adviceComputedBadge);
    expect(container).toHaveTextContent(copy.computeEcho(copy.computeEchoStates.device));
    expect(posted).toHaveLength(1);
    // The button stays, to solve again.
    expect(deviceButton()).toBeEnabled();
    expect(container).not.toHaveTextContent("%");
  });

  it("says beside the heading that it is solving while the run it started goes on", async () => {
    const { page } = memberPage(() => new StillSolving());
    const { container } = render(page(DEVICE_MENU));
    await waitFor(() => expect(deviceState(container)).toBe("solving"));
    const decision = screen.getByRole("region", { name: copy.decisionTitle });
    expect(decision).toHaveTextContent(copy.deviceSolving);
    expect(deviceButton()).toBeDisabled();
  });

  it("solves nothing once the deadline has passed", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container } = render(
      page({ ...DEVICE_MENU, fixtures: CLOSED_WEEK, deadlinePassed: "2020-01-01T00:00:00Z" }),
    );
    await act(async () => {});
    expect(screen.getByTestId("deadline-passed")).toBeInTheDocument();
    expect(posted).toHaveLength(0);
    expect(deviceState(container)).toBeNull();
    expect(container).not.toHaveTextContent(DONE);
  });

  it("solves nothing while the calendar does not state the deadline", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container } = render(page({ ...DEVICE_MENU, fixtures: null }));
    await act(async () => {});
    expect(posted).toHaveLength(0);
    expect(deviceState(container)).toBeNull();
    expect(deviceButton()).toBeEnabled();
  });

  it("waits for the index to say no plan is published", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container, rerender } = render(
      page({ ...DEVICE_MENU, index: null, adviceIssue: "index-missing", adviceLoading: true }),
    );
    await act(async () => {});
    expect(posted).toHaveLength(0);
    rerender(page(DEVICE_MENU));
    await waitFor(() => expect(container).toHaveTextContent(DONE));
    expect(posted).toHaveLength(1);
  });

  it.each<MemberTool>(["what-if", "card"])(
    "solves the plan when the visitor lands on the %s page's address",
    async (tool) => {
      const { page, posted } = memberPage(() => new CannedSolver());
      render(page({ ...DEVICE_MENU, tool }));
      if (tool === "what-if") {
        expect(await screen.findByRole("button", { name: copy.whatIfStart })).toBeEnabled();
      } else {
        await waitFor(() => expect(screen.queryByText(copy.toolEmpty)).toBeNull());
      }
      expect(posted).toHaveLength(1);
    },
  );

  it("says on a tool page that it is solving, not that there is nothing", async () => {
    const { page } = memberPage(() => new StillSolving());
    render(page({ ...DEVICE_MENU, tool: "card" }));
    expect(await screen.findByText(copy.deviceSolving)).toBeInTheDocument();
    expect(screen.queryByText(copy.toolEmpty)).toBeNull();
  });
});

describe("the member page with a published one-week plan", () => {
  it.each([
    ["the full menu", PUBLISHED_INDEX],
    ["an index from before the menu", { ...PUBLISHED_INDEX, menu: undefined }],
  ])("keeps the button and solves nothing on opening under %s", async (_, index) => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container } = render(page({ ...DEVICE_MENU, index, adviceIssue: "published-missing" }));
    await act(async () => {});
    expect(posted).toHaveLength(0);
    expect(deviceState(container)).toBeNull();
    expect(deviceButton()).toBeEnabled();
    await act(async () => deviceButton()!.click());
    await waitFor(() => expect(container).toHaveTextContent(DONE));
    expect(posted).toHaveLength(1);
  });

  it("solves nothing on a tool page's address either", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    render(page({ ...DEVICE_MENU, index: PUBLISHED_INDEX, tool: "card", adviceIssue: undefined }));
    await act(async () => {});
    expect(posted).toHaveLength(0);
    expect(screen.getByText(copy.toolEmpty)).toBeInTheDocument();
  });
});

describe("one run at a time for a run started on opening", () => {
  it("posts one solve when the page's effects are mounted twice", async () => {
    const { page, posted } = memberPage(() => new CannedSolver(), true);
    const { container } = render(page(DEVICE_MENU));
    await waitFor(() => expect(container).toHaveTextContent(DONE));
    await act(async () => {});
    expect(posted).toHaveLength(1);
  });

  it("goes on solving as late reads land and the visitor moves to a tool page and back", async () => {
    const workers: StillSolving[] = [];
    const { page, posted } = memberPage(() => {
      const made = new StillSolving();
      workers.push(made);
      return made;
    });
    const { container, rerender } = render(page(DEVICE_MENU));
    await waitFor(() => expect(deviceState(container)).toBe("solving"));
    // A late advice read, a late index read of the same menu and the calendar read again.
    rerender(page({ ...DEVICE_MENU, adviceLoading: true }));
    rerender(page({ ...DEVICE_MENU, adviceIssue: "published-missing" }));
    rerender(page({ ...DEVICE_MENU, index: { ...DEVICE_INDEX }, fixtures: { ...OPEN_WEEK } }));
    rerender(page({ ...DEVICE_MENU, tool: "card" }));
    rerender(page(DEVICE_MENU));
    await act(async () => {});
    expect(deviceState(container)).toBe("solving");
    expect(workers).toHaveLength(1);
    expect(workers[0]!.terminated).toBe(false);
    expect(posted).toHaveLength(1);
  });

  it("does not start again when the member asks the service instead", async () => {
    const { page, posted } = memberPage(() => new CannedSolver());
    const { container } = render(
      page({ ...DEVICE_MENU, capabilities: SERVICE, computeService: "ready" }),
    );
    await waitFor(() => expect(container).toHaveTextContent(DONE));
    await act(async () => screen.getByRole("button", { name: copy.computeButton }).click());
    await waitFor(() =>
      expect(container).toHaveTextContent(copy.computeEcho(copy.computeEchoStates.done)),
    );
    expect(container).not.toHaveTextContent(DONE);
    expect(posted).toHaveLength(1);
  });

  it("ends with a new selection and solves the selection it returns to", async () => {
    const workers: StillSolving[] = [];
    const { page, posted } = memberPage(() => {
      const made = new StillSolving();
      workers.push(made);
      return made;
    });
    const { container } = render(page(DEVICE_MENU));
    await waitFor(() => expect(deviceState(container)).toBe("solving"));
    // A three-week window is not the device's to solve: the run ends and none starts.
    await act(async () => screen.getByText("to-3").click());
    expect(workers[0]!.terminated).toBe(true);
    expect(posted).toHaveLength(1);
    await act(async () => screen.getByText("to-1").click());
    await waitFor(() => expect(deviceState(container)).toBe("solving"));
    expect(posted).toHaveLength(2);
    expect(workers).toHaveLength(2);
    expect(workers[1]!.terminated).toBe(false);
  });
});
