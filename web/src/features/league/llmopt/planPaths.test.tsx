import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { checkedPreferences } from "../advice/decisionPreferences";
import type { ComputePhase } from "../advice/useAdviceJob";
import { LLMOPT_COPY } from "./copy";
import { preparePlans } from "./intent";
import { PlanPathGroups } from "./PlanPathGroups";
import { delayedBuyPreferences } from "./planPaths";
import { baseDraft, prepareRun, requestFor } from "./planRun";
import { followupRequests, restoredSlot } from "./planSlots";

afterEach(cleanup);

it("delays the actual purchase and preserves mandatory and timed rules", () => {
  const original = checkedPreferences({
    no_hits: true,
    keep_players: [12],
    week_rules: [{ week: 2, rules: { buy_players: [91], no_hits: true } }],
  });
  const delayed = delayedBuyPreferences(original, [92]);
  expect(delayed).toMatchObject({
    no_hits: true,
    keep_players: [12],
    hold_opening_transfers: true,
    week_rules: [{ week: 2, rules: { buy_players: [91, 92], no_hits: true } }],
  });
  expect(original.week_rules?.[0]?.rules.buy_players).toEqual([91]);
  expect(
    delayedBuyPreferences(
      checkedPreferences({ week_rules: [{ week: 2, rules: { hold_transfers: true } }] }),
      [92],
    ),
  ).toBeNull();
  expect(
    delayedBuyPreferences(
      checkedPreferences({
        frozen_weeks: [{ week: 2, transfers_in: [], transfers_out: [], chip: null }],
      }),
      [92],
    ),
  ).toBeNull();
});

it("keeps the disabled request behavior and restores at most two enabled paths", () => {
  const squad = mockEntrySquadEnvelopes[35249001]!.payload;
  const held = new Set([...squad.starting_xi, ...squad.bench].map((p) => p.player_id));
  const draft = { window: 3 as const, hard: [], soft: [] };
  const inputs = {
    draft,
    held,
    request: requestFor(squad, false, 3),
    plans: preparePlans(baseDraft(draft), held),
    wildcardNotHeld: false,
  };
  const plan = mockEntryAdviceEnvelope(35249001, "saf-puan", 3).payload;
  plan.bank_after_tenths = 20;
  const disabled = followupRequests(prepareRun(inputs), plan);
  expect(disabled.map((f) => f?.alternative.kind)).toEqual(["roll", "bank"]);
  const run = prepareRun({ ...inputs, paths3w: true });
  const enabled = followupRequests(run, plan);
  expect(enabled).toHaveLength(2);
  expect(enabled[0]?.alternative.kind).toBe("delay");
  expect(
    enabled[0]?.request.preferences.week_rules?.find((w) => w.week === 2)?.rules.buy_players,
  ).toEqual(plan.plan_weeks![0]!.transfers_in.map((p) => p.player_id));
  expect(restoredSlot(run, 0, enabled[0]?.alternative)).toEqual(enabled[0]?.request);
  expect(restoredSlot(prepareRun(inputs), 0, enabled[0]?.alternative)).toBeNull();
});

it("groups later paths by the opening decision only when enabled", () => {
  const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
  const later = structuredClone(envelope);
  later.payload.plan_weeks![1]!.chip = "bboost";
  const state = (value: typeof envelope): ComputePhase => ({
    phase: "done",
    source: "api-cache",
    request: { leagueId: 1, entryId: 1, strategy: "saf-puan", window: 3 },
    envelope: value,
  });
  function Card({ title }: { title: string; state: ComputePhase }) {
    return <article>{title}</article>;
  }
  const cards = [
    <Card key="first" title="First" state={state(envelope)} />,
    <Card key="later" title="Later" state={state(later)} />,
  ];
  const view = render(
    <PlanPathGroups enabled={false} className="plans" label={(n) => `Opening ${n}`}>
      {cards}
    </PlanPathGroups>,
  );
  expect(screen.queryByRole("heading")).toBeNull();
  view.rerender(
    <PlanPathGroups enabled className="plans" label={(n) => `Opening ${n}`}>
      {cards}
    </PlanPathGroups>,
  );
  expect(screen.getAllByRole("heading")).toHaveLength(1);
  expect(screen.getAllByRole("article")).toHaveLength(2);
});

const pathRequest = { leagueId: 1, entryId: 1, strategy: "saf-puan", window: 3 } as const;

function completedPath(chip: "bboost" | "3xc" | null): Extract<ComputePhase, { phase: "done" }> {
  const envelope = structuredClone(mockEntryAdviceEnvelope(35249001, "saf-puan", 3));
  envelope.payload.plan_weeks![0]!.chip = chip;
  return { phase: "done", source: "api-cache", request: pathRequest, envelope };
}

function PathCard({ name }: { name: string; state: ComputePhase; conflict?: boolean }) {
  return <article aria-label={name}>{name}</article>;
}

it.each([
  ["en", "delay", "bank"],
  ["tr", "bank", "delay"],
] as const)(
  "keeps cards and announced decisions as %s paths resolve in %s, %s order",
  (lang, first, second) => {
    const label = LLMOPT_COPY[lang].openingDecision;
    const pending: ComputePhase = { phase: "requesting", request: pathRequest };
    const paths: Record<"bank" | "delay", ComputePhase> = { bank: pending, delay: pending };
    const draw = (
      runId: string,
      baseVisible: boolean,
      combined: ComputePhase,
      conflict = false,
      hideFirst = false,
    ) => (
      <PlanPathGroups enabled runId={runId} className="plans" label={label}>
        {baseVisible && <PathCard name="base" state={pending} />}
        {(["bank", "delay"] as const)
          .filter((slot) => !hideFirst || slot !== first)
          .map((slot) => (
            <PathCard key={slot} name={slot} state={paths[slot]} />
          ))}
        <PathCard name="combined" state={combined} conflict={conflict} />
      </PlanPathGroups>
    );
    const view = render(draw("one", true, pending));
    const article = (name: string) => screen.getByRole("article", { name });
    function members(index: number) {
      const group = screen.getByRole("region", { name: label(index) });
      return group
        .getAttribute("aria-owns")!
        .split(" ")
        .map((id) => document.getElementById(id)!.querySelector("article"));
    }
    const initially = {
      first: article(first),
      second: article(second),
      combined: article("combined"),
    };
    expect(screen.queryByRole("region")).toBeNull();
    paths[first] = completedPath("bboost");
    view.rerender(draw("one", false, pending));
    expect(members(1)).toEqual([initially.first]);
    expect(article(first)).toBe(initially.first);
    expect(article(second)).toBe(initially.second);
    paths[second] = completedPath("3xc");
    view.rerender(draw("one", true, completedPath("bboost"), true));
    expect(members(1)).toEqual([initially.first]);
    expect(members(2)).toEqual([initially.second]);
    expect(article("combined")).toBe(initially.combined);
    view.rerender(draw("one", false, completedPath("bboost")));
    expect(members(1)).toEqual([initially.first, initially.combined]);
    expect(article("combined")).toBe(initially.combined);
    expect(members(2)).toEqual([initially.second]);
    paths[first] = { phase: "failed", request: pathRequest };
    view.rerender(draw("one", false, pending));
    expect(screen.queryByRole("region", { name: label(1) })).toBeNull();
    expect(members(2)).toEqual([initially.second]);
    expect(article(first)).toBe(initially.first);
    view.rerender(draw("one", false, pending, false, true));
    expect(members(2)).toEqual([initially.second]);
    expect(article(second)).toBe(initially.second);
    view.rerender(draw("two", false, pending));
    expect(members(1)).toEqual([article(second)]);
    expect(screen.queryByRole("region", { name: label(2) })).toBeNull();
  },
);

it("leaves incomplete timelines and failed or unavailable solver answers outside opening decisions", () => {
  const incomplete = completedPath(null);
  incomplete.envelope.payload.plan_weeks!.shift();
  const infeasible = completedPath(null);
  infeasible.envelope.payload.solver_status = "INFEASIBLE";
  render(
    <PlanPathGroups enabled className="plans" label={LLMOPT_COPY.en.openingDecision}>
      <PathCard name="partial" state={incomplete} />
      <PathCard name="no plan" state={infeasible} />
      <PathCard name="unavailable" state={{ phase: "unavailable", request: pathRequest }} />
      <PathCard name="idle" state={{ phase: "idle" }} />
    </PlanPathGroups>,
  );
  expect(screen.getAllByRole("article")).toHaveLength(4);
  expect(screen.queryByRole("region")).toBeNull();
  expect(screen.queryByRole("heading")).toBeNull();
});
