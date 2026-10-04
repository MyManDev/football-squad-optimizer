/**
 * The device solve on the page: offered for the one selection the publisher wrote inputs
 * for, run through a worker, shown as the advice document the page reads, held to the
 * capture on screen, and dropped by a new selection or a service computation.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { withLeague } from "../../../testSupport/league";
import { isAdvicePayload } from "../advice/adviceShape";
import type { AdviceRequest } from "../advice/adviceClient";
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import type { DevicePlanReply, DevicePlanRequest } from "./devicePlan.worker";
import type { LpSolver } from "./lp/problem";
import { solvePlan } from "./solve/week";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";
import {
  deviceChip,
  deviceSolvable,
  useDevicePlan,
  type DeviceSolver,
  type DevicePlanPhase,
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
  leagueId: document.league_id,
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

function Harness({
  squad,
  request,
  loadDocument,
  solver,
  onState,
}: {
  squad: EntrySquad;
  request: AdviceRequest;
  loadDocument: () => Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  solver: DeviceSolver;
  onState: (state: DevicePlanPhase) => void;
}) {
  const device = useDevicePlan(squad, request, {
    loadDocument,
    createSolver: () => solver,
    now: () => new Date("2026-10-03T01:02:03Z"),
  });
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

describe("what the device can solve", () => {
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
