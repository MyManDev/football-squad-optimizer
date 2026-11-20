import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  addHistory,
  checkedHistory,
  currentPlanCommand,
  EMPTY_HISTORY,
  planCatalogue,
  planIdentity,
  retainedPlan,
  selectHistory,
  verifiedHistory,
} from "./planHistory";
import { commandDraft } from "./planCommand";
import { intentAnswer, preparePlans } from "./intent";
import { prepareRun, requestFor } from "./planRun";
import { freezeReference } from "./planRevision";

const ENTRY = 35249001;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
const make = (window: 1 | 3 = 1) => ({
  ...mockEntryAdviceEnvelope(ENTRY, "saf-puan", window).payload,
  plan_data_id: "a".repeat(64),
});
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

it("keeps a content identity across reload, recomputation, timing, names and unordered starters", async () => {
  const p = make();
  const id = await planIdentity(p);
  const clone = structuredClone(p);
  clone.solver_status = "FEASIBLE";
  clone.optimality_gap = 123;
  clone.starting_xi?.reverse();
  clone.moves.reverse();
  clone.captain!.name = "Translated";
  expect(await planIdentity(clone)).toBe(id);
  expect(await planIdentity(JSON.parse(JSON.stringify(p)))).toBe(id);
});
it("changes identity for resources, scores, bench order, later transfers and data", async () => {
  const p = make(3),
    id = await planIdentity(p);
  for (const change of [
    (p: ReturnType<typeof make>) => {
      p.bank_after_tenths = (p.bank_after_tenths ?? 0) + 1;
    },
    (p: ReturnType<typeof make>) => {
      p.plan_weeks![2]!.expected_points += 0.1;
    },
    (p: ReturnType<typeof make>) => {
      p.bench!.reverse();
    },
    (p: ReturnType<typeof make>) => {
      p.plan_weeks![2]!.chip = "wildcard";
    },
    (p: ReturnType<typeof make>) => {
      p.plan_data_id = "b".repeat(64);
    },
  ]) {
    const clone = structuredClone(p);
    change(clone);
    expect(await planIdentity(clone)).not.toBe(id);
  }
});
it("retains only known computed fields and rejects a corrupted saved content identity", async () => {
  const p = make();
  Object.assign(p, { api_key: "sentinel", provider: "sentinel" });
  Object.assign(p.captain!, { api_key: "sentinel" });
  const safe = retainedPlan(p);
  expect(JSON.stringify(safe)).not.toContain("sentinel");
  const h = addHistory(EMPTY_HISTORY, [{ id: await planIdentity(p), plan: safe }]);
  expect(await verifiedHistory(checkedHistory(JSON.parse(JSON.stringify(h)), squad))).toEqual(h);
  h.items[0]!.plan.bank_after_tenths = 999;
  expect(await verifiedHistory(h)).toEqual(EMPTY_HISTORY);
});
it("retains at most twelve plans and permits selection, undo and returning without a calculation", async () => {
  const plans = await Promise.all(
    Array.from({ length: 14 }, async (_, i) => {
      const plan = make();
      plan.bank_after_tenths = i;
      return { id: await planIdentity(plan), plan };
    }),
  );
  const h = addHistory(EMPTY_HISTORY, plans);
  expect(h.items).toHaveLength(12);
  const first = selectHistory(h, plans[2]!.id),
    second = selectHistory(first, plans[7]!.id);
  const restored = await verifiedHistory(checkedHistory(JSON.parse(JSON.stringify(second)), squad));
  expect(restored.navigation[restored.cursor]).toBe(plans[7]!.id);
  expect(restored.navigation[restored.cursor - 1]).toBe(plans[2]!.id);
  expect(selectHistory(restored, plans[2]!.id).items).toEqual(restored.items);
});
it("catalogues only current data, in visible order, without computed figures", async () => {
  const p = make(),
    q = make();
  q.bank_after_tenths = 999;
  const old = make();
  old.plan_data_id = "c".repeat(64);
  const items = await Promise.all(
    [p, q, old].map(async (plan) => ({ id: await planIdentity(plan), plan })),
  );
  const h = selectHistory(addHistory(EMPTY_HISTORY, items), items[0]!.id);
  const catalogue = planCatalogue(h, [q, p])!;
  expect(catalogue.plans.map((p) => p.plan_id)).toEqual([items[1]!.id, items[0]!.id]);
  expect(JSON.stringify(catalogue)).not.toMatch(/bank|points|999/);
  expect(catalogue.plans[0]!.weeks[0]!.players).toHaveLength(15);
});
it("resolves a checked label against the sent catalogue and verifies its current content", async () => {
  const plans = [make(3), make(3), make(3)];
  const rows = await Promise.all(
    plans.map(async (plan, i) => {
      plan.bank_after_tenths = i + 10;
      return { id: await planIdentity(plan), plan };
    }),
  );
  const history = addHistory(EMPTY_HISTORY, rows);
  const sent = planCatalogue(history, plans)!;
  const id = rows[1]!.id;
  const response = { status: "plan", command: { plan_id: id, action: "select" }, plan_label: "P2" };
  expect(intentAnswer(response, [], sent)).toEqual({ status: "plan", command: response.command });
  expect(intentAnswer({ status: "plan", command: response.command }, [], sent)).toEqual({
    status: "plan",
    command: response.command,
  });
  const restored = await verifiedHistory(
    checkedHistory(JSON.parse(JSON.stringify(history)), squad),
  );
  expect(currentPlanCommand(sent, planCatalogue(restored, plans), id)).toBe(true);
  expect(
    currentPlanCommand(sent, planCatalogue(history, [plans[1]!, plans[0]!, plans[2]!]), id),
  ).toBe(false);
  expect(currentPlanCommand(sent, { ...sent, data_id: "f".repeat(64) }, id)).toBe(false);
  expect(currentPlanCommand(sent, undefined, id)).toBe(false);
  for (const label of ["P1", "P4", "P02", id, null])
    expect(() => intentAnswer({ ...response, plan_label: label }, [], sent)).toThrow();
  expect(() => intentAnswer(response, [])).toThrow();
});
it("derives frozen weeks and substitutions from computed decisions", async () => {
  const p = make(3),
    item = { id: await planIdentity(p), plan: p };
  const h = addHistory(EMPTY_HISTORY, [item]),
    cat = planCatalogue(h, [p])!;
  const players = [...p.starting_xi!, ...p.bench!].map((p) => ({
    id: p.player_id,
    name: p.name,
    team: p.team,
  }));
  const frozen = commandDraft(
    { plan_id: item.id, action: "freeze_week", week: 2 },
    cat,
    p,
    { hard: [], soft: [] },
    players,
  );
  expect(freezeReference(frozen.reference, frozen.draft!.keep_weeks)[0]!.transfers_in).toEqual(
    p.plan_weeks![1]!.transfers_in.map((p) => p.player_id),
  );
  players.push({ id: 990099, name: "Replacement", team: "Arsenal" });
  const result = commandDraft(
    {
      plan_id: item.id,
      action: "substitute",
      week: 1,
      player_id: p.starting_xi![0]!.player_id,
      replacement_id: 990099,
    },
    cat,
    p,
    { hard: [], soft: [] },
    players,
  );
  expect(result.draft!.hard).toContainEqual({ kind: "include_player", player_id: 990099, week: 1 });
  expect(result.reference.compareOnly).toBe(true);
  const draft = result.draft!;
  const held = new Set([...squad.starting_xi, ...squad.bench].map((p) => p.player_id));
  const run = prepareRun({
    draft,
    held,
    plans: preparePlans(draft, held),
    request: requestFor(squad, false, 3),
    wildcardNotHeld: false,
    reference: result.reference,
    compareOnly: result.reference.compareOnly,
  });
  expect(run.baseRequest).not.toBeNull();
  expect(run.automaticBasis).toBeNull();
  expect(run.slots).toHaveLength(0);
  expect(result.reference.net).toBe(frozen.reference.net);
  expect(() =>
    commandDraft(
      { plan_id: "d".repeat(64), action: "select" },
      cat,
      p,
      { hard: [], soft: [] },
      players,
    ),
  ).toThrow();
});
