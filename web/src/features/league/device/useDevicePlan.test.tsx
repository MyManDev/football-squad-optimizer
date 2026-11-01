/**
 * The device solve on the page: offered for the one selection the publisher wrote inputs
 * for, run through a worker, shown as the advice document the page reads, held to the
 * capture on screen, started once while a run loads or solves, dropped by a new
 * selection or a service computation, and marked on the page's timeline.
 */

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { stubTree, withLeague } from "../../../testSupport/league";
import { isAdvicePayload } from "../advice/adviceShape";
import type { AdviceRequest } from "../advice/adviceClient";
import type { LeagueTree } from "../data";
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import type { DevicePlanReply, DevicePlanRequest } from "./deviceSolver.worker";
import type { LpSolver } from "./lp/problem";
import {
  DEVICE_LOAD_ALLOWANCE_SECONDS,
  DEVICE_REPLY_GRACE_SECONDS,
  DEVICE_SOLVE_CEILING_SECONDS,
} from "./solve/ceiling";
import { replyTo } from "./replies";
import { solvePlan } from "./solve/week";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";
import {
  deviceChip,
  deviceSolvable,
  useDevicePlan,
  type DeviceSolver,
  type DevicePlanPhase,
  type DeviceTimeline,
  type PageVisibility,
} from "./useDevicePlan";

afterEach(cleanup);

const require = createRequire(import.meta.url);
let highs: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  highs = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const document = fixture.document as unknown as DevicePlanDocument;
const member = fixture.members[1]!;
const entry = member.entry as unknown as DevicePlanEntry;
const ENTRY_ID = 35249001;

function squadWith(
  block: DevicePlanEntry | null,
  snapshot = document.source_snapshot_id,
): EntrySquad {
  const base = mockEntrySquadEnvelopes[ENTRY_ID]!.payload;
  return { ...base, source_snapshot_id: snapshot, device_plan: block };
}

const REQUEST: AdviceRequest = {
  // The fixture is a tree's copy (v1), which names its league.
  leagueId: document.league_id!,
  entryId: ENTRY_ID,
  strategy: "saf-puan",
  window: 1,
};

/** The worker, answered in process with the real solver. */
class InProcessSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  terminated = false;
  private readonly answer?: (request: DevicePlanRequest) => DevicePlanReply;
  constructor(answer?: (request: DevicePlanRequest) => DevicePlanReply) {
    this.answer = answer;
  }
  postMessage(request: DevicePlanRequest): void {
    // As the worker does: ready once the solver is loaded, then the answer.
    const ready: DevicePlanReply = { id: request.id, kind: "ready" };
    const reply: DevicePlanReply = this.answer
      ? this.answer(request)
      : {
          id: request.id,
          kind: "answer",
          answer: solvePlan(highs, request.document, request.entry, () => 0),
        };
    queueMicrotask(() => {
      this.onmessage?.({ data: ready } as MessageEvent<DevicePlanReply>);
      this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
    });
  }
  terminate(): void {
    this.terminated = true;
  }
}

function envelope(payload: DevicePlanDocument): LeagueViewEnvelope<DevicePlanDocument> {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-03T00:00:00Z",
    source_kind: "live",
    payload,
  };
}

/** Timers the test fires by hand: each callback with the delay it was set for. */
class HandTimers {
  private next = 0;
  readonly waiting = new Map<number, { callback: () => void; milliseconds: number }>();
  readonly set = (callback: () => void, milliseconds: number): unknown => {
    this.next += 1;
    this.waiting.set(this.next, { callback, milliseconds });
    return this.next;
  };
  readonly clear = (handle: unknown): void => {
    this.waiting.delete(handle as number);
  };
  /** Fire every timer still set, as if its delay had passed. */
  fireAll(): void {
    const due = [...this.waiting.values()];
    this.waiting.clear();
    for (const timer of due) timer.callback();
  }
}

/** A worker that loads and then never answers. */
class SilentSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
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

/** A worker that loads and answers only when the test says, keeping each request posted to it. */
class HeldSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  readonly posted: DevicePlanRequest[] = [];
  postMessage(request: DevicePlanRequest): void {
    this.posted.push(request);
    queueMicrotask(() =>
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>),
    );
  }
  /** Answer a request posted earlier with the real solver's plan. */
  answer(request: DevicePlanRequest): void {
    this.onmessage?.({
      data: {
        id: request.id,
        kind: "answer",
        answer: solvePlan(highs, request.document, request.entry, () => 0),
      },
    } as MessageEvent<DevicePlanReply>);
  }
  terminate(): void {}
}

/** A timeline kept in order; a measure needs both its marks, as User Timing's does. */
class KeptTimeline implements DeviceTimeline {
  readonly marks: string[] = [];
  readonly measures: { name: string; start: string; end: string }[] = [];
  /** Every measure asked for, kept or not. */
  readonly asked: string[] = [];
  mark(name: string): void {
    this.marks.push(name);
  }
  measure(name: string, start: string, end: string): void {
    this.asked.push(name);
    if (!this.marks.includes(start) || !this.marks.includes(end)) {
      throw new Error(`no mark ${start} or ${end}`);
    }
    this.measures.push({ name, start, end });
  }
}

/** The names the marks of the run whose press is `press` take: `device:<n>:<point>`. */
function marksOf(press: string): (point: string) => string {
  const run = /^device:(\d+):press$/.exec(press)?.[1];
  return (point) => `device:${run}:${point}`;
}

/** A worker that never loads: it answers nothing, not even that it is ready. */
class MuteSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  terminated = false;
  postMessage(): void {}
  terminate(): void {
    this.terminated = true;
  }
}

/** A page the test hides and shows, keeping each listener it is given until it is removed. */
class HandVisibility implements PageVisibility {
  private state: DocumentVisibilityState = "visible";
  readonly listeners = new Set<() => void>();
  readonly hidden = (): boolean => this.state === "hidden";
  readonly listen = (changed: () => void): (() => void) => {
    // One entry for each listener added, even one added twice.
    const listener = () => changed();
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  /** Hide or show the page and tell each listener, as the browser's visibilitychange does. */
  turn(state: DocumentVisibilityState): void {
    this.state = state;
    for (const listener of [...this.listeners]) listener();
  }
}

/** A clock in milliseconds that moves only when the test moves it. */
class HandClock {
  milliseconds = 0;
  readonly read = (): number => this.milliseconds;
}

function Harness({
  squad,
  request,
  loadDocument,
  solver,
  onState,
  rivals,
  createSolver,
  timers,
  inlineTimers = false,
  timeline,
  visibility,
  clock,
}: {
  squad: EntrySquad;
  request: AdviceRequest;
  /** Absent, the league's tree reads the document, as on the page. */
  loadDocument?: () => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  solver: DeviceSolver;
  onState: (state: DevicePlanPhase) => void;
  rivals?: readonly number[];
  createSolver?: () => DeviceSolver;
  timers?: HandTimers;
  /** Pass the timers as new functions on every render, as a caller writing them inline does. */
  inlineTimers?: boolean;
  /** Absent, the page's own User Timing. */
  timeline?: DeviceTimeline;
  /** Absent, the page's own visibility and clock. */
  visibility?: PageVisibility;
  clock?: () => number;
}) {
  const timerDependencies = !timers
    ? {}
    : inlineTimers
      ? {
          setTimer: (callback: () => void, milliseconds: number) =>
            timers.set(callback, milliseconds),
          clearTimer: (handle: unknown) => timers.clear(handle),
        }
      : { setTimer: timers.set, clearTimer: timers.clear };
  const device = useDevicePlan(
    squad,
    request,
    {
      ...(loadDocument ? { loadDocument } : {}),
      createSolver: createSolver ?? (() => solver),
      now: () => new Date("2026-10-03T01:02:03Z"),
      ...timerDependencies,
      timeline,
      visibility,
      clock,
    },
    rivals,
  );
  onState(device.state);
  return (
    <div>
      <output data-testid="available">{String(device.available)}</output>
      <output data-testid="phase">{device.state.phase}</output>
      <button type="button" onClick={device.run}>
        run
      </button>
      <button type="button" onClick={device.reset}>
        reset
      </button>
    </div>
  );
}

describe("the worker", () => {
  it("ships under its own file name, not the one an edge holds broken", () => {
    // The browser caches the built file by name; devicePlan.worker's was cached as HTML.
    const source = readFileSync(join(__dirname, "useDevicePlan.ts"), "utf8");
    expect(source).toContain('new URL("./deviceSolver.worker.ts", import.meta.url)');
    expect(source).not.toContain("devicePlan.worker");
    expect(existsSync(join(__dirname, "deviceSolver.worker.ts"))).toBe(true);
    expect(existsSync(join(__dirname, "devicePlan.worker.ts"))).toBe(false);
  });

  it("solves every request within the device's ceiling", () => {
    // The worker cannot load here (its wasm comes from the built assets), so its wiring is
    // read from its source; the ceiling itself is tested in solve/ceiling.test.ts.
    const source = readFileSync(join(__dirname, "deviceSolver.worker.ts"), "utf8");
    expect(source).toContain("replyTo(withinCeiling(loaded), event.data,");
  });
});

describe("the device's inputs", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("are asked of the league's tree for the capture the member's page shows", async () => {
    // A directory read before a later publish can still name the earlier capture's table;
    // the tree reads that table only for the capture it is asked for.
    const devicePlan = vi
      .fn<LeagueTree["devicePlan"]>()
      .mockImplementation(async () => envelope(document));
    stubTree({ devicePlan });
    const squad = squadWith(entry);
    render(
      withLeague(
        <Harness
          squad={squad}
          request={REQUEST}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(devicePlan).toHaveBeenCalledWith(squad.source_snapshot_id);
  });
});

describe("what the device can solve", () => {
  it("offers a rival strategy only against a rival the statement names", () => {
    const rivalRequest: AdviceRequest = {
      ...REQUEST,
      strategy: "ortak-koru",
      rivalEntryId: 35249002,
    };
    const mount = (rivals?: readonly number[]) =>
      render(
        withLeague(
          <Harness
            squad={squadWith(entry)}
            request={rivalRequest}
            loadDocument={async () => envelope(document)}
            solver={new InProcessSolver()}
            onState={() => {}}
            rivals={rivals}
          />,
        ),
      );
    mount([35249002]);
    expect(screen.getByTestId("available")).toHaveTextContent("true");
    cleanup();
    mount([35249004]);
    expect(screen.getByTestId("available")).toHaveTextContent("false");
    cleanup();
    mount([]);
    expect(screen.getByTestId("available")).toHaveTextContent("false");
  });

  const squad = squadWith(entry);

  it("is the pure-points plan over one week, a held chip, or a rival strategy", () => {
    expect(deviceSolvable(REQUEST, squad)).toBe(true);
    expect(deviceSolvable({ ...REQUEST, window: 3 }, squad)).toBe(false);
    expect(deviceSolvable({ ...REQUEST, strategy: "ortak-koru", rivalEntryId: 2 }, squad)).toBe(
      true,
    );
    expect(deviceSolvable({ ...REQUEST, strategy: "ortak-koru" }, squad)).toBe(false);
    expect(deviceSolvable({ ...REQUEST, top100Weight: 20 }, squad)).toBe(false);
    expect(deviceSolvable({ ...REQUEST, managersWord: true }, squad)).toBe(false);
    expect(deviceSolvable({ ...REQUEST, chip: "bboost" }, squad)).toBe(true);
    expect(deviceSolvable({ ...REQUEST, model: "football" }, squad)).toBe(false);
  });

  it("takes a chip only where the squad document says the member can still play it", () => {
    const used = structuredClone(squad);
    used.chips!.states.bboost!.first_half!.state = "used";
    expect(deviceChip({ ...REQUEST, chip: "bboost" }, used)).toBeUndefined();
    expect(deviceChip({ ...REQUEST, chip: "3xc" }, used)).toBe("3xc");
    expect(deviceChip(REQUEST, used)).toBeNull();
    // A history the producer could not read offers no chip at all.
    const unknown = { ...squad, chips: { known: false, gameweek: squad.gameweek, states: {} } };
    expect(deviceChip({ ...REQUEST, chip: "3xc" }, unknown)).toBeUndefined();
    expect(deviceChip({ ...REQUEST, chip: "3xc" }, { ...squad, chips: undefined })).toBeUndefined();
    expect(deviceChip({ ...REQUEST, chip: "auto" }, squad)).toBeUndefined();
  });

  it("is offered only where the publisher wrote the member's inputs", () => {
    const states: DevicePlanPhase[] = [];
    const { rerender } = render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={(s) => states.push(s)}
        />,
      ),
    );
    expect(screen.getByTestId("available")).toHaveTextContent("true");
    rerender(
      withLeague(
        <Harness
          squad={squadWith(null)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={(s) => states.push(s)}
        />,
      ),
    );
    expect(screen.getByTestId("available")).toHaveTextContent("false");
    rerender(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={{ ...REQUEST, window: 5 }}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={(s) => states.push(s)}
        />,
      ),
    );
    expect(screen.getByTestId("available")).toHaveTextContent("false");
  });
});

describe("a solve on the device", () => {
  it("loads, solves in the worker and shows the advice document the page reads", async () => {
    const seen = { latest: { phase: "idle" } as DevicePlanPhase };
    const solver = new InProcessSolver();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={solver}
          onState={(s) => {
            seen.latest = s;
          }}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    const latest = seen.latest;
    expect(latest.phase).toBe("done");
    if (latest.phase !== "done") return;
    const payload = latest.envelope.payload;
    expect(isAdvicePayload(payload)).toBe(true);
    expect(payload.entry_id).toBe(ENTRY_ID);
    expect(payload.mode).toBe("saf-puan");
    expect(payload.window).toBe(1);
    expect(payload.source_snapshot_id).toBe(document.source_snapshot_id);
    expect(payload.solver_status).toBe("OPTIMAL");
    expect(payload.moves.map((m) => [m.player_out?.player_id, m.player_in?.player_id])).toEqual(
      member.reference.moves.map((m) => [m.out, m.in]),
    );
    expect(payload.captain?.player_id).toBe(member.reference.captain);
    expect(payload.vice_captain?.player_id).toBe(member.reference.vice_captain);
    expect(payload.starting_xi?.map((p) => p.player_id).sort((a, b) => a - b)).toEqual(
      member.reference.starting_xi,
    );
    expect(payload.bench?.map((p) => p.player_id)).toEqual(member.reference.bench);
    expect(payload.transfer_hit_points).toBe(member.reference.transfer_hit_points);
    expect(payload.expected_gain_vs_hold).toBeCloseTo(member.reference.expected_gain_vs_hold!, 9);
    expect(payload.expected_own_points).toBeCloseTo(member.reference.expected_own_points, 9);
    expect(latest.envelope.generated_at_utc).toBe("2026-10-03T01:02:03Z");
    expect(latest.envelope.source_kind).toBe("live");
  });

  it("refuses inputs from another capture than the page's", async () => {
    render(
      withLeague(
        <Harness
          squad={squadWith(entry, "another-capture")}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("other-capture"));
  });

  it("says when the publish carries no inputs, and when the read fails", async () => {
    const { rerender } = render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => {
            throw new LeagueDataMissing("device-plan.json");
          }}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("unpublished"));
    rerender(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={{ ...REQUEST, gameweek: 9 }}
          loadDocument={async () => {
            throw new LeagueDataError("broken");
          }}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
  });

  it("shows a refusal as a refusal and a crash as a failure, never a plan", async () => {
    const refusing = new InProcessSolver((request) => ({
      id: request.id,
      kind: "refused",
      status: "Infeasible",
      stage: "plan",
    }));
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={refusing}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("refused"));
    // One worker per page: a crash is seen on a page of its own.
    cleanup();
    const crashing = new InProcessSolver((request) => ({ id: request.id, kind: "failed" }));
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={crashing}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());

    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
  });

  it("answers a worker that cannot load as a failure and makes a fresh one next time", async () => {
    class Dead implements DeviceSolver {
      onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      terminated = false;
      postMessage(): void {
        queueMicrotask(() => this.onerror?.({ message: "script failed" }));
      }
      terminate(): void {
        this.terminated = true;
      }
    }
    const made: Dead[] = [];
    function Page() {
      const device = useDevicePlan(squadWith(entry), REQUEST, {
        loadDocument: async () => envelope(document),
        createSolver: () => {
          const next = new Dead();
          made.push(next);
          return next;
        },
      });
      return (
        <div>
          <output data-testid="phase">{device.state.phase}</output>
          <button type="button" onClick={device.run}>
            run
          </button>
        </div>
      );
    }
    render(withLeague(<Page />));
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(made).toHaveLength(1);
    expect(made[0]!.terminated).toBe(true);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(made).toHaveLength(2);
  });

  it("drops a run that reset interrupts while its inputs are still loading", async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => {
            await gate;
            return envelope(document);
          }}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    await act(async () => screen.getByText("reset").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await act(async () => {
      release!();
      await gate;
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
  });

  it("is dropped by a new selection and by reset, and a late reply for the old one is ignored", async () => {
    let release: (() => void) | null = null;
    const slow = new InProcessSolver();
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const loader = async () => {
      await gate;
      return envelope(document);
    };
    const { rerender } = render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={loader}
          solver={slow}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    rerender(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={{ ...REQUEST, window: 3 }}
          loadDocument={loader}
          solver={slow}
          onState={() => {}}
        />,
      ),
    );
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await act(async () => {
      release!();
      await gate;
    });
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");

    rerender(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={loader}
          solver={slow}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    await act(async () => screen.getByText("reset").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
  });
});

describe("a solve that runs too long, or is no longer wanted", () => {
  /** A page whose workers load and never answer, each kept in `created`. */
  function silentPage(
    timers: HandTimers,
    created: DeviceSolver[],
    request: AdviceRequest = REQUEST,
    loadDocument: () => Promise<LeagueViewEnvelope<DevicePlanDocument>> = async () =>
      envelope(document),
  ) {
    return withLeague(
      <Harness
        squad={squadWith(entry)}
        request={request}
        loadDocument={loadDocument}
        solver={new SilentSolver()}
        createSolver={() => {
          const made = new SilentSolver();
          created.push(made);
          return made;
        }}
        timers={timers}
        onState={() => {}}
      />,
    );
  }

  async function solving(timers: HandTimers, created: DeviceSolver[]) {
    const view = render(silentPage(timers, created));
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    return view;
  }

  it("ends a worker that never loads, after the load's allowance and a grace, and fails the run", async () => {
    const timers = new HandTimers();
    const created: MuteSolver[] = [];
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new MuteSolver()}
          createSolver={() => {
            const made = new MuteSolver();
            created.push(made);
            return made;
          }}
          timers={timers}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(timers.waiting.size).toBe(1));
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    // Until the solver says it is ready, the one watchdog waits the load's allowance and
    // the grace, not the solve's ceiling.
    expect([...timers.waiting.values()].map((timer) => timer.milliseconds)).toEqual([
      (DEVICE_LOAD_ALLOWANCE_SECONDS + DEVICE_REPLY_GRACE_SECONDS) * 1000,
    ]);
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(created).toHaveLength(1);
    expect(created[0]!.terminated).toBe(true);
    expect(timers.waiting.size).toBe(0);
  });

  it("leaves no solving phase behind a selection the member leaves and returns to", async () => {
    const timers = new HandTimers();
    const created: SilentSolver[] = [];
    const { rerender } = await solving(timers, created);
    rerender(silentPage(timers, created, { ...REQUEST, window: 3 }));
    rerender(silentPage(timers, created, REQUEST));
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(created).toHaveLength(1);
    expect(created[0]!.terminated).toBe(true);
    expect(timers.waiting.size).toBe(0);
  });

  it("leaves no loading phase behind a selection left while its inputs were still read", async () => {
    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const loader = async () => {
      await gate;
      return envelope(document);
    };
    const timers = new HandTimers();
    const created: SilentSolver[] = [];
    const { rerender } = render(silentPage(timers, created, REQUEST, loader));
    await act(async () => screen.getByText("run").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    rerender(silentPage(timers, created, { ...REQUEST, window: 3 }, loader));
    rerender(silentPage(timers, created, REQUEST, loader));
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await act(async () => {
      release!();
      await gate;
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(created).toHaveLength(0);
    expect(timers.waiting.size).toBe(0);
  });

  it("keeps a run going when the caller passes new timer functions on every render", async () => {
    const timers = new HandTimers();
    const solver = new InProcessSolver();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={solver}
          timers={timers}
          inlineTimers
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(solver.terminated).toBe(false);
    expect(timers.waiting.size).toBe(0);
  });

  it("ends a worker that never answers, after the solve's ceiling and a grace, and fails the run", async () => {
    const timers = new HandTimers();
    const created: SilentSolver[] = [];
    await solving(timers, created);
    // Once the solver has loaded, the watchdog waits the ceiling and the grace, no less.
    expect([...timers.waiting.values()].map((timer) => timer.milliseconds)).toEqual([
      (DEVICE_SOLVE_CEILING_SECONDS + DEVICE_REPLY_GRACE_SECONDS) * 1000,
    ]);
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(created).toHaveLength(1);
    expect(created[0]!.terminated).toBe(true);
  });

  it("ends the worker of a solve that a reset interrupts, and the next run makes a fresh one", async () => {
    const timers = new HandTimers();
    const created: SilentSolver[] = [];
    await solving(timers, created);
    await act(async () => screen.getByText("reset").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(created[0]!.terminated).toBe(true);
    expect(timers.waiting.size).toBe(0);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    expect(created).toHaveLength(2);
    expect(created[1]!.terminated).toBe(false);
  });

  it("ends the worker of a solve that a new selection interrupts", async () => {
    const timers = new HandTimers();
    const created: SilentSolver[] = [];
    const { rerender } = await solving(timers, created);
    rerender(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={{ ...REQUEST, window: 3 }}
          loadDocument={async () => envelope(document)}
          solver={new SilentSolver()}
          createSolver={() => new SilentSolver()}
          timers={timers}
          onState={() => {}}
        />,
      ),
    );
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(created[0]!.terminated).toBe(true);
    expect(timers.waiting.size).toBe(0);
  });

  it("does not end a worker whose solve has already answered", async () => {
    const timers = new HandTimers();
    const solver = new InProcessSolver();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={solver}
          timers={timers}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(timers.waiting.size).toBe(0);
    await act(async () => screen.getByText("reset").click());
    expect(solver.terminated).toBe(false);
  });
});

describe("a watchdog on a page the member hides", () => {
  const LOAD = (DEVICE_LOAD_ALLOWANCE_SECONDS + DEVICE_REPLY_GRACE_SECONDS) * 1000;
  const SOLVE = (DEVICE_SOLVE_CEILING_SECONDS + DEVICE_REPLY_GRACE_SECONDS) * 1000;

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** The delays of the timers still set. */
  const delays = (timers: HandTimers) =>
    [...timers.waiting.values()].map((timer) => timer.milliseconds);

  /** A page with its own timers, visibility and clock, whose workers are kept in `created`. */
  function hiddenPage<Solver extends DeviceSolver>(make: () => Solver) {
    const timers = new HandTimers();
    const visibility = new HandVisibility();
    const clock = new HandClock();
    const timeline = new KeptTimeline();
    const created: Solver[] = [];
    const page = (request: AdviceRequest = REQUEST) =>
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={request}
          loadDocument={async () => envelope(document)}
          solver={make()}
          createSolver={() => {
            const made = make();
            created.push(made);
            return made;
          }}
          timers={timers}
          visibility={visibility}
          clock={clock.read}
          timeline={timeline}
          onState={() => {}}
        />,
      );
    return { timers, visibility, clock, timeline, created, page };
  }

  it("pauses the solve's watchdog while the page is hidden and sets it again for what was left", async () => {
    const { timers, visibility, clock, created, page } = hiddenPage(() => new SilentSolver());
    render(page());
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    expect(delays(timers)).toEqual([SOLVE]);
    clock.milliseconds += 40_000;
    act(() => visibility.turn("hidden"));
    expect(timers.waiting.size).toBe(0);
    // However long the page stays hidden, none of it is counted.
    clock.milliseconds += 600_000;
    act(() => visibility.turn("visible"));
    expect(delays(timers)).toEqual([SOLVE - 40_000]);
    clock.milliseconds += 25_000;
    act(() => visibility.turn("hidden"));
    clock.milliseconds += 5_000;
    act(() => visibility.turn("visible"));
    expect(delays(timers)).toEqual([SOLVE - 65_000]);
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(created).toHaveLength(1);
    expect(created[0]!.terminated).toBe(true);
    expect(visibility.listeners.size).toBe(0);
  });

  it("pauses the load's allowance the same way while the worker is still loading", async () => {
    const { timers, visibility, clock, created, page } = hiddenPage(() => new MuteSolver());
    render(page());
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(timers.waiting.size).toBe(1));
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    expect(delays(timers)).toEqual([LOAD]);
    clock.milliseconds += 20_000;
    act(() => visibility.turn("hidden"));
    expect(timers.waiting.size).toBe(0);
    clock.milliseconds += 300_000;
    act(() => visibility.turn("visible"));
    expect(delays(timers)).toEqual([LOAD - 20_000]);
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    expect(created).toHaveLength(1);
    expect(created[0]!.terminated).toBe(true);
    expect(visibility.listeners.size).toBe(0);
  });

  it.each([
    { worker: "still loading", make: (): DeviceSolver => new MuteSolver(), point: "posted" },
    { worker: "ready", make: (): DeviceSolver => new SilentSolver(), point: "ready" },
  ])(
    "sets nothing for a run started on a hidden page until it is shown, then the whole span for a worker $worker",
    async ({ make, point }) => {
      const { timers, visibility, clock, timeline, page } = hiddenPage(make);
      visibility.turn("hidden");
      render(page());
      await act(async () => screen.getByText("run").click());
      await waitFor(() => expect(timeline.marks.at(-1)).toMatch(new RegExp(`:${point}$`)));
      expect(timers.waiting.size).toBe(0);
      expect(visibility.listeners.size).toBe(1);
      clock.milliseconds += 90_000;
      act(() => visibility.turn("visible"));
      expect(delays(timers)).toEqual([point === "posted" ? LOAD : SOLVE]);
      await act(async () => timers.fireAll());
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
      expect(visibility.listeners.size).toBe(0);
    },
  );

  it.each(
    (["an answer", "a reset", "a new selection", "an unmount"] as const).flatMap((ending) =>
      (["visible", "hidden"] as const).map((state) => ({ ending, state })),
    ),
  )("leaves no listener and no timer after $ending on a $state page", async ({ ending, state }) => {
    const { timers, visibility, created, page } = hiddenPage(() => new HeldSolver());
    const view = render(page());
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    expect(visibility.listeners.size).toBe(1);
    act(() => visibility.turn(state));
    expect(timers.waiting.size).toBe(state === "visible" ? 1 : 0);
    if (ending === "an answer") {
      await act(async () => created[0]!.answer(created[0]!.posted[0]!));
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    } else if (ending === "a reset") {
      await act(async () => screen.getByText("reset").click());
    } else if (ending === "a new selection") {
      view.rerender(page({ ...REQUEST, window: 3 }));
    } else {
      view.unmount();
    }
    expect(visibility.listeners.size).toBe(0);
    expect(timers.waiting.size).toBe(0);
    // A page shown again sets nothing for a run that has ended.
    act(() => visibility.turn("visible"));
    expect(timers.waiting.size).toBe(0);
  });

  it("hears the page's own visibility when given none", async () => {
    const timers = new HandTimers();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new SilentSolver()}
          timers={timers}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    const page = globalThis.document;
    const shown = vi.spyOn(page, "visibilityState", "get").mockReturnValue("hidden");
    act(() => {
      page.dispatchEvent(new Event("visibilitychange"));
    });
    expect(timers.waiting.size).toBe(0);
    shown.mockReturnValue("visible");
    act(() => {
      page.dispatchEvent(new Event("visibilitychange"));
    });
    expect(timers.waiting.size).toBe(1);
    expect(delays(timers)[0]).toBeLessThanOrEqual(SOLVE);
    // A reset takes its listener off the page: the page shown again sets nothing.
    await act(async () => screen.getByText("reset").click());
    act(() => {
      page.dispatchEvent(new Event("visibilitychange"));
    });
    expect(timers.waiting.size).toBe(0);
  });
});

describe("a run asked for again while one is in flight", () => {
  /** A gate the inputs' read waits on, and how many reads were made. */
  function heldReads() {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const reads = { count: 0 };
    const loadDocument = async () => {
      reads.count += 1;
      await gate;
      return envelope(document);
    };
    return { reads, loadDocument, release };
  }

  /** Reads of the inputs that each wait on a gate of their own, released one at a time. */
  function gatedReads() {
    const gates: (() => void)[] = [];
    const loadDocument = () =>
      new Promise<LeagueViewEnvelope<DevicePlanDocument>>((resolve) => {
        gates.push(() => resolve(envelope(document)));
      });
    return { gates, loadDocument };
  }

  async function pressTwice() {
    await act(async () => {
      screen.getByText("run").click();
      screen.getByText("run").click();
    });
  }

  it("posts nothing more to a worker that is solving, and the first run still finishes", async () => {
    const timers = new HandTimers();
    const created: HeldSolver[] = [];
    let reads = 0;
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => {
            reads += 1;
            return envelope(document);
          }}
          solver={new HeldSolver()}
          createSolver={() => {
            const made = new HeldSolver();
            created.push(made);
            return made;
          }}
          timers={timers}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    await act(async () => screen.getByText("run").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("solving");
    expect(created).toHaveLength(1);
    expect(created[0]!.posted).toHaveLength(1);
    expect(reads).toBe(1);
    await act(async () => created[0]!.answer(created[0]!.posted[0]!));
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(timers.waiting.size).toBe(0);
  });

  it("reads the inputs once when asked again while they are still being read", async () => {
    const { reads, loadDocument, release } = heldReads();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={loadDocument}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await act(async () => screen.getByText("run").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    expect(reads.count).toBe(1);
    await act(async () => release());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(reads.count).toBe(1);
  });

  it.each(["a reset", "a new selection"])("starts one new run at once after %s", async (cause) => {
    const { reads, loadDocument, release } = heldReads();
    const page = (request: AdviceRequest) =>
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={request}
          loadDocument={loadDocument}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      );
    const { rerender } = render(page(REQUEST));
    await act(async () => screen.getByText("run").click());
    // The first run is still reading its inputs when it is interrupted.
    if (cause === "a reset") await act(async () => screen.getByText("reset").click());
    else rerender(page({ ...REQUEST, gameweek: 9 }));
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await pressTwice();
    expect(screen.getByTestId("phase")).toHaveTextContent("loading");
    expect(reads.count).toBe(2);
    await act(async () => release());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(reads.count).toBe(2);
  });

  it.each(["a reset", "a new selection"])(
    "still starts nothing beside the run after %s when the run it ended settles late",
    async (cause) => {
      const { gates, loadDocument } = gatedReads();
      const page = (request: AdviceRequest) =>
        withLeague(
          <Harness
            squad={squadWith(entry)}
            request={request}
            loadDocument={loadDocument}
            solver={new InProcessSolver()}
            onState={() => {}}
          />,
        );
      const { rerender } = render(page(REQUEST));
      await act(async () => screen.getByText("run").click());
      if (cause === "a reset") await act(async () => screen.getByText("reset").click());
      else rerender(page({ ...REQUEST, gameweek: 9 }));
      await act(async () => screen.getByText("run").click());
      expect(gates).toHaveLength(2);
      // The ended run's read lands and that run settles while the next is still reading.
      await act(async () => gates[0]!());
      expect(screen.getByTestId("phase")).toHaveTextContent("loading");
      await act(async () => screen.getByText("run").click());
      expect(gates).toHaveLength(2);
      await act(async () => gates[1]!());
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
      expect(gates).toHaveLength(2);
    },
  );

  it.each([
    { ending: "done", answer: undefined },
    {
      ending: "failed",
      answer: (request: DevicePlanRequest): DevicePlanReply => ({ id: request.id, kind: "failed" }),
    },
    {
      ending: "refused",
      answer: (request: DevicePlanRequest): DevicePlanReply => ({
        id: request.id,
        kind: "refused",
        status: "Infeasible",
        stage: "plan",
      }),
    },
  ])("starts one new run at once after a run that ended $ending", async ({ ending, answer }) => {
    let reads = 0;
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => {
            reads += 1;
            return envelope(document);
          }}
          solver={new InProcessSolver(answer)}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent(ending));
    expect(reads).toBe(1);
    await pressTwice();
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent(ending));
    expect(reads).toBe(2);
  });
});

describe("the marks a run leaves", () => {
  const FINISHED = ["press", "inputs", "posted", "ready", "answer"];

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("marks each stage of a finished run in order and measures the three between them", async () => {
    const timeline = new KeptTimeline();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    const at = marksOf(timeline.marks[0]!);
    expect(timeline.marks).toEqual(FINISHED.map(at));
    expect(timeline.measures).toEqual([
      { name: "device:inputs", start: at("press"), end: at("inputs") },
      { name: "device:load", start: at("posted"), end: at("ready") },
      { name: "device:solve", start: at("ready"), end: at("answer") },
    ]);
  });

  it("leaves no solve measured when the load's watchdog ends the run", async () => {
    const timers = new HandTimers();
    const timeline = new KeptTimeline();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new MuteSolver()}
          timers={timers}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(timers.waiting.size).toBe(1));
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    const at = marksOf(timeline.marks[0]!);
    expect(timeline.marks).toEqual(["press", "inputs", "posted", "failed"].map(at));
    expect(timeline.measures.map((measure) => measure.name)).toEqual(["device:inputs"]);
    // Not asked for at all, rather than asked for and lost for want of its start.
    expect(timeline.asked).toEqual(["device:inputs"]);
  });

  it("measures the solve to the failure when the solve's watchdog ends the run", async () => {
    const timers = new HandTimers();
    const timeline = new KeptTimeline();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new SilentSolver()}
          timers={timers}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    await act(async () => timers.fireAll());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("failed"));
    const at = marksOf(timeline.marks[0]!);
    expect(timeline.marks).toEqual(["press", "inputs", "posted", "ready", "failed"].map(at));
    expect(timeline.measures.at(-1)).toEqual({
      name: "device:solve",
      start: at("ready"),
      end: at("failed"),
    });
  });

  it.each(["a reset", "a new selection"])(
    "leaves no reply mark and no solve measured for a run %s ends while it solves",
    async (cause) => {
      const timers = new HandTimers();
      const timeline = new KeptTimeline();
      const page = (request: AdviceRequest) =>
        withLeague(
          <Harness
            squad={squadWith(entry)}
            request={request}
            loadDocument={async () => envelope(document)}
            solver={new SilentSolver()}
            timers={timers}
            timeline={timeline}
            onState={() => {}}
          />,
        );
      const { rerender } = render(page(REQUEST));
      await act(async () => screen.getByText("run").click());
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
      if (cause === "a reset") await act(async () => screen.getByText("reset").click());
      else rerender(page({ ...REQUEST, window: 3 }));
      // The ended run's wait settles empty, and the run goes no further.
      await act(async () => {});
      expect(screen.getByTestId("phase")).toHaveTextContent("idle");
      const at = marksOf(timeline.marks[0]!);
      expect(timeline.marks).toEqual(["press", "inputs", "posted", "ready"].map(at));
      expect(timeline.asked).toEqual(["device:inputs", "device:load"]);
    },
  );

  it("marks a refusal as the reply that ended the solve", async () => {
    const timeline = new KeptTimeline();
    const refusing = new InProcessSolver((request) => ({
      id: request.id,
      kind: "refused",
      status: "Infeasible",
      stage: "plan",
    }));
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={refusing}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("refused"));
    const at = marksOf(timeline.marks[0]!);
    expect(timeline.marks).toEqual(["press", "inputs", "posted", "ready", "refused"].map(at));
    expect(timeline.measures.at(-1)).toEqual({
      name: "device:solve",
      start: at("ready"),
      end: at("refused"),
    });
  });

  it("keeps two runs apart: one a reset ended leaves only its press, the next its own marks", async () => {
    const gates: (() => void)[] = [];
    const loadDocument = () =>
      new Promise<LeagueViewEnvelope<DevicePlanDocument>>((resolve) => {
        gates.push(() => resolve(envelope(document)));
      });
    const timeline = new KeptTimeline();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={loadDocument}
          solver={new InProcessSolver()}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await act(async () => screen.getByText("reset").click());
    await act(async () => screen.getByText("run").click());
    // The ended run's inputs land while the next run is still reading its own.
    await act(async () => gates[0]!());
    await act(async () => gates[1]!());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    const first = marksOf(timeline.marks[0]!);
    const next = marksOf(timeline.marks[1]!);
    expect(next("press")).not.toBe(first("press"));
    expect(timeline.marks).toEqual([first("press"), ...FINISHED.map(next)]);
    expect(timeline.measures.map(({ start, end }) => [start, end])).toEqual([
      [next("press"), next("inputs")],
      [next("posted"), next("ready")],
      [next("ready"), next("answer")],
    ]);
  });

  it("marks nothing for a press the run in flight ignores", async () => {
    const timeline = new KeptTimeline();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          timeline={timeline}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => {
      screen.getByText("run").click();
      screen.getByText("run").click();
    });
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(timeline.marks).toEqual(FINISHED.map(marksOf(timeline.marks[0]!)));
  });

  it("names a run's marks apart from those of a run on the page before it was mounted again", async () => {
    const timeline = new KeptTimeline();
    for (let mounted = 0; mounted < 2; mounted += 1) {
      render(
        withLeague(
          <Harness
            squad={squadWith(entry)}
            request={REQUEST}
            loadDocument={async () => envelope(document)}
            solver={new InProcessSolver()}
            timeline={timeline}
            onState={() => {}}
          />,
        ),
      );
      await act(async () => screen.getByText("run").click());
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
      cleanup();
    }
    const first = marksOf(timeline.marks[0]!);
    const next = marksOf(timeline.marks[FINISHED.length]!);
    expect(next("press")).not.toBe(first("press"));
    expect(timeline.marks).toEqual([...FINISHED.map(first), ...FINISHED.map(next)]);
  });

  it("finishes a run whose timeline throws on every call as it finishes one whose does not", async () => {
    const answer = solvePlan(highs, document, entry, () => 0);
    const calls = { count: 0 };
    const throwing: DeviceTimeline = {
      mark: () => {
        calls.count += 1;
        throw new Error("no marks here");
      },
      measure: () => {
        calls.count += 1;
        throw new Error("no measures here");
      },
    };
    async function finished(timeline: DeviceTimeline): Promise<DevicePlanPhase> {
      const seen = { latest: { phase: "idle" } as DevicePlanPhase };
      render(
        withLeague(
          <Harness
            squad={squadWith(entry)}
            request={REQUEST}
            loadDocument={async () => envelope(document)}
            solver={new InProcessSolver((request) => ({ id: request.id, kind: "answer", answer }))}
            timeline={timeline}
            onState={(state) => {
              seen.latest = state;
            }}
          />,
        ),
      );
      await act(async () => screen.getByText("run").click());
      await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
      cleanup();
      return seen.latest;
    }
    const kept = await finished(new KeptTimeline());
    expect(await finished(throwing)).toEqual(kept);
    // Five marks and three measures were asked for, and every one of them threw.
    expect(calls.count).toBe(8);
  });

  it("leaves its marks and measures on the page's own User Timing when given no timeline", async () => {
    performance.clearMarks();
    performance.clearMeasures();
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    const named = (type: string) =>
      performance
        .getEntriesByType(type)
        .map(({ name }) => name)
        .filter((name) => name.startsWith("device:"));
    expect(named("measure")).toEqual(["device:inputs", "device:load", "device:solve"]);
    const marks = named("mark");
    expect(marks).toEqual(FINISHED.map(marksOf(marks[0]!)));
  });

  it("finishes a run on a page whose browser has no User Timing", async () => {
    vi.stubGlobal("performance", { now: performance.now.bind(performance) });
    render(
      withLeague(
        <Harness
          squad={squadWith(entry)}
          request={REQUEST}
          loadDocument={async () => envelope(document)}
          solver={new InProcessSolver()}
          onState={() => {}}
        />,
      ),
    );
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
  });
});

describe("the chip timing's gains", () => {
  /** The worker, answered in process through its own replies, keeping each request. */
  class ReplyingSolver implements DeviceSolver {
    onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
    readonly posted: DevicePlanRequest[] = [];
    terminate(): void {}
    postMessage(request: DevicePlanRequest): void {
      this.posted.push(request);
      const replies: DevicePlanReply[] = [{ id: request.id, kind: "ready" }];
      replyTo(
        highs,
        request,
        (reply) => replies.push(reply),
        () => 0,
      );
      queueMicrotask(() => {
        for (const reply of replies)
          this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
      });
    }
  }

  /**
   * A worker that posts ready and the plain plan at once, and the gains only when the test
   * releases them, as many times as it likes and for whichever run.
   */
  class HeldGainsSolver implements DeviceSolver {
    onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
    readonly posted: DevicePlanRequest[] = [];
    terminated = false;
    terminate(): void {
      this.terminated = true;
    }
    /** Hold the plan too, until `releasePlan`. */
    holdPlan = false;
    postMessage(request: DevicePlanRequest): void {
      this.posted.push(request);
      queueMicrotask(() => {
        this.onmessage?.({
          data: { id: request.id, kind: "ready" },
        } as MessageEvent<DevicePlanReply>);
        if (!this.holdPlan) this.releasePlan(this.posted.length - 1);
      });
    }
    /** The plain plan of the request posted `index`th. */
    releasePlan(index: number): void {
      const request = this.posted[index]!;
      const plan = { ...solvePlan(highs, request.document, request.entry, () => 0), seconds: 0.4 };
      this.onmessage?.({
        data: { id: request.id, kind: "plan", answer: plan },
      } as MessageEvent<DevicePlanReply>);
    }
    /** A chip of the request posted `index`th tried: `done` of `total`. */
    count(index: number, done: number, total: number): void {
      this.onmessage?.({
        data: { id: this.posted[index]!.id, kind: "chip", done, total },
      } as MessageEvent<DevicePlanReply>);
    }
    /** The gains of the request posted `index`th, or a run that failed after its plan. */
    release(index: number, gains: Record<string, number | null> | null = { wildcard: 9 }): void {
      this.onmessage?.({
        data: { id: this.posted[index]!.id, kind: "gains", gains, seconds: 3.2 },
      } as MessageEvent<DevicePlanReply>);
    }
  }

  function mount(
    squad: EntrySquad,
    request: AdviceRequest,
    solver: DeviceSolver,
    timers?: HandTimers,
  ) {
    const seen = { latest: { phase: "idle" } as DevicePlanPhase };
    const view = (asked: AdviceRequest) =>
      withLeague(
        <Harness
          squad={squad}
          request={asked}
          loadDocument={async () => envelope(document)}
          solver={solver}
          timers={timers}
          onState={(s) => {
            seen.latest = s;
          }}
        />,
      );
    const { rerender } = render(view(request));
    return { seen, rerender: (asked: AdviceRequest) => rerender(view(asked)) };
  }

  async function runOnce(squad: EntrySquad, request: AdviceRequest, solver: DeviceSolver) {
    const { seen } = mount(squad, request, solver);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    return seen;
  }

  it("are asked with the plain plan, each held chip once, and the run keeps them with its table", async () => {
    const solver = new ReplyingSolver();
    const seen = await runOnce(squadWith(entry), REQUEST, solver);
    // The example member holds all four chips in the first half, so all four are solved.
    expect(solver.posted.map((request) => request.chipGains)).toEqual([
      ["wildcard", "freehit", "bboost", "3xc"],
    ]);
    await waitFor(() =>
      expect(seen.latest.phase === "done" && seen.latest.chipTiming).toBeTruthy(),
    );
    const latest = seen.latest;
    if (latest.phase !== "done") throw new Error("The run did not finish.");
    expect(latest.chipTiming?.table).toBe(document);
    expect(Object.keys(latest.chipTiming?.gains ?? {})).toEqual([
      "wildcard",
      "freehit",
      "bboost",
      "3xc",
    ]);
    // The plan shown is still the plain plan.
    expect(latest.envelope.payload.chip ?? null).toBeNull();
  });

  it("follow the plan: it is shown first, with its own time, and the gains do not change it", async () => {
    const solver = new HeldGainsSolver();
    const seen = await runOnce(squadWith(entry), REQUEST, solver);
    const first = seen.latest;
    if (first.phase !== "done") throw new Error("The plan was not shown.");
    expect(first.chipTiming).toBeNull();
    // The timing line counts the plain plan's solve only, as before the chip timing.
    expect(first.seconds).toBe(0.4);
    await act(async () => solver.release(0));
    const after = seen.latest;
    if (after.phase !== "done") throw new Error("The plan was lost.");
    expect(after.chipTiming?.gains).toEqual({ wildcard: 9 });
    expect(after.seconds).toBe(0.4);
    expect(after.envelope).toBe(first.envelope);
  });

  it("are dropped for a run a reset or a new selection ended", async () => {
    const solver = new HeldGainsSolver();
    const { seen, rerender } = mount(squadWith(entry), REQUEST, solver);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    await act(async () => screen.getByText("reset").click());
    await act(async () => solver.release(0));
    expect(seen.latest).toEqual({ phase: "idle" });
    // Again, and this time the member moves to a three-week window before the gains come.
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    expect(solver.terminated).toBe(true);
    rerender({ ...REQUEST, window: 3 });
    await act(async () => solver.release(1));
    expect(seen.latest).toEqual({ phase: "idle" });
    // And back: the hook still holds that run's plan for this selection (the page resets
    // it on a new selection), but the gains that run never received do not surface.
    rerender(REQUEST);
    await act(async () => solver.release(1));
    expect(seen.latest).toMatchObject({ phase: "done", chipTiming: null });
  });

  it("are never another run's: an ended run's plan and gains reach no later run", async () => {
    const solver = new HeldGainsSolver();
    const { seen } = mount(squadWith(entry), REQUEST, solver);
    solver.holdPlan = true;
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    await act(async () => screen.getByText("reset").click());
    // The ended run's plan comes late: the page stays as the reset left it.
    await act(async () => solver.releasePlan(0));
    expect(seen.latest).toEqual({ phase: "idle" });
    solver.holdPlan = false;
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    // The first run's gains reach the same worker's next run, which does not take them.
    await act(async () => solver.release(0, { wildcard: 99 }));
    expect(seen.latest).toMatchObject({ phase: "done", chipTiming: null });
    await act(async () => solver.release(1));
    expect(seen.latest.phase === "done" && seen.latest.chipTiming?.gains).toEqual({ wildcard: 9 });
  });

  it("keep the plan, with no chip timing, when the run fails or is stopped after it", async () => {
    const solver = new HeldGainsSolver();
    const seen = await runOnce(squadWith(entry), REQUEST, solver);
    await act(async () => solver.release(0, null));
    expect(seen.latest).toMatchObject({ phase: "done", chipTiming: null });
    cleanup();
    const timers = new HandTimers();
    const held = new HeldGainsSolver();
    const stopped = mount(squadWith(entry), REQUEST, held, timers);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("done"));
    // The solve's watchdog ends the worker before the gains arrive.
    await act(async () => timers.fireAll());
    expect(held.terminated).toBe(true);
    await act(async () => held.release(0));
    expect(stopped.seen.latest).toMatchObject({ phase: "done", chipTiming: null });
  });

  it("are not asked with a chip, and that run carries none", async () => {
    const solver = new ReplyingSolver();
    const seen = await runOnce(squadWith(entry), { ...REQUEST, chip: "3xc" }, solver);
    expect(solver.posted).toHaveLength(1);
    expect(solver.posted[0]!.chipGains).toBeUndefined();
    expect(seen.latest.phase === "done" && seen.latest.chipTiming).toBeNull();
  });

  it("are not asked where the member holds no chip or the history is unknown", async () => {
    const base = squadWith(entry);
    const spent = {
      ...base,
      chips: {
        ...base.chips!,
        states: Object.fromEntries(
          Object.entries(base.chips!.states).map(([name, halves]) => [
            name,
            { ...halves, first_half: { ...halves!.first_half!, state: "used" as const } },
          ]),
        ),
      },
    };
    for (const squad of [spent, { ...base, chips: { ...base.chips!, known: false } }]) {
      const solver = new ReplyingSolver();
      const seen = await runOnce(squad, REQUEST, solver);
      expect(solver.posted[0]!.chipGains).toBeUndefined();
      expect(seen.latest.phase === "done" && seen.latest.chipTiming).toBeNull();
      cleanup();
    }
  });

  const progressOf = (state: DevicePlanPhase) =>
    "progress" in state ? (state.progress ?? null) : null;

  it("count the run's stages: inputs, solver and plan, then each chip, never elapsed time", async () => {
    const timers = new HandTimers();
    const solver = new SilentSolver();
    const { seen } = mount(squadWith(entry), REQUEST, solver, timers);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("solving"));
    // The member holds all four chips: three stages before them, then one for each.
    expect(progressOf(seen.latest)).toEqual({
      step: "plan",
      done: 2,
      total: 7,
      chips: { done: 0, total: 4 },
    });
  });

  it("count each chip after the plan is shown, and stop counting when the gains arrive", async () => {
    const solver = new HeldGainsSolver();
    const seen = await runOnce(squadWith(entry), REQUEST, solver);
    expect(progressOf(seen.latest)).toEqual({
      step: "chips",
      done: 3,
      total: 7,
      chips: { done: 0, total: 4 },
    });
    act(() => solver.count(0, 1, 4));
    expect(progressOf(seen.latest)).toEqual({
      step: "chips",
      done: 4,
      total: 7,
      chips: { done: 1, total: 4 },
    });
    // The plan shown does not change while the chips are counted.
    expect(seen.latest.phase === "done" && seen.latest.chipTiming).toBeNull();
    await act(async () => solver.release(0));
    await waitFor(() => expect(progressOf(seen.latest)).toBeNull());
    expect(seen.latest.phase === "done" && seen.latest.chipTiming).toBeTruthy();
  });

  it("stop counting when the run fails after its plan, and keep the plan", async () => {
    const solver = new HeldGainsSolver();
    const seen = await runOnce(squadWith(entry), REQUEST, solver);
    await act(async () => solver.release(0, null));
    await waitFor(() => expect(progressOf(seen.latest)).toBeNull());
    expect(seen.latest.phase).toBe("done");
  });

  it("stop counting when the member leaves the selection while its chips are tried", async () => {
    const solver = new HeldGainsSolver();
    const { seen, rerender } = mount(squadWith(entry), REQUEST, solver);
    await act(async () => screen.getByText("run").click());
    await waitFor(() => expect(progressOf(seen.latest)?.step).toBe("chips"));
    rerender({ ...REQUEST, strategy: "saf-puan", window: 3 });
    rerender(REQUEST);
    expect(progressOf(seen.latest)).toBeNull();
  });
});
