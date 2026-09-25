import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { DecisionWorkbench } from "./DecisionWorkbench";
import {
  decisionCandidate,
  decisionMetrics,
  decisionParams,
  loadDecisionBoard,
  saveDecisionBoard,
} from "./decisionBoard";
import type { AdviceRequest } from "./adviceClient";

const squad = mockEntrySquadEnvelopes[35249001]!;
const request: AdviceRequest = {
  leagueId: 352490,
  entryId: 35249001,
  strategy: "saf-puan",
  window: 3,
};
const answer = (window: 3 | 5 = 3) => {
  const envelope = mockEntryAdviceEnvelope(request.entryId, "saf-puan", window);
  envelope.payload.squad_basis = squad.payload.squad_basis;
  return envelope;
};
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("nets hits once and refuses to invent missing hits or incomplete horizon totals", () => {
  const p = answer().payload;
  p.expected_own_points = 55;
  p.expected_gain_vs_hold = 3;
  p.transfer_hit_points = 4;
  p.plan_weeks!.forEach((w, i) => {
    w.expected_points = 50 + i;
    w.transfer_hit_points = i === 0 ? 4 : 0;
  });
  expect(decisionMetrics(p)).toMatchObject({ net: 51, gain: -1, horizonNet: 149, horizonHits: 4 });
  delete p.transfer_hit_points;
  expect(decisionMetrics(p)).toMatchObject({ net: null, gain: null });
  p.plan_weeks!.pop();
  expect(decisionMetrics(p).horizonNet).toBeNull();
});

it("refuses stale baselines, other captures, other switches, and unsolved plans", () => {
  expect(decisionCandidate(answer(), request, squad)).not.toBeNull();
  expect(decisionCandidate(answer(), { ...request, window: 5 }, squad)).toBeNull();
  expect(decisionCandidate(answer(), { ...request, top100Weight: 20 }, squad)).toBeNull();
  expect(decisionCandidate(answer(), { ...request, model: "football" }, squad)).toBeNull();
  expect(decisionCandidate(answer(), { ...request, chip: "auto" }, squad)).toBeNull();
  for (const patch of [
    { source_snapshot_id: "old" },
    { solver_status: "UNKNOWN" },
    { squad_basis: "pre_free_hit_gw01" },
    { bench: [] },
  ]) {
    const changed = answer();
    Object.assign(changed.payload, patch);
    expect(decisionCandidate(changed, request, squad)).toBeNull();
  }
});

it("restores validated preferences only for the same squad, bank, rights and capture", () => {
  const candidate = decisionCandidate(answer(), request, squad)!;
  saveDecisionBoard(squad, {
    candidates: [candidate],
    preferred: candidate.id,
    note: "Wait for team news",
  });
  expect(loadDecisionBoard(squad).preferred).toBe(candidate.id);
  for (const patch of [{ bank_tenths: 99 }, { free_transfers: 4 }, { source_snapshot_id: "new" }]) {
    const changed = structuredClone(squad);
    Object.assign(changed.payload, patch);
    expect(loadDecisionBoard(changed).candidates).toEqual([]);
  }
  const key = `squadopt.decision-board:${request.leagueId}:${request.entryId}`;
  const saved = JSON.parse(sessionStorage.getItem(key)!);
  saved.candidates[0].envelope.payload.source_snapshot_id = "tampered";
  sessionStorage.setItem(key, JSON.stringify(saved));
  expect(loadDecisionBoard(squad).preferred).toBeNull();
  sessionStorage.setItem(key, "broken");
  expect(loadDecisionBoard(squad).candidates).toEqual([]);
});

it("restores every setting, removes old switches, and preserves unrelated URL fields", () => {
  const params = decisionParams(
    new URLSearchParams("model=football&llm=on&chip=auto&rival=123&top100=20&foo=bar"),
    request,
  );
  expect(params.toString()).toBe("foo=bar&mode=saf-puan&window=3");
  const all = {
    ...request,
    model: "football" as const,
    managersWord: true,
    top100Weight: 40,
    rivalEntryId: 7,
    chip: null,
  };
  expect(decisionParams(params, all).get("llm")).toBe("on");
  expect(decisionParams(params, all).get("top100")).toBe("40");
});

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}
function card(r = request, selected = answer(), context = squad) {
  return (
    <MemoryRouter>
      <LanguageProvider initialLanguage="tr">
        <Location />
        <DecisionWorkbench request={r} selected={selected} squad={context} />
      </LanguageProvider>
    </MemoryRouter>
  );
}

it("pins alternatives, records a human preference, restores it and resets on changed resources", () => {
  const view = render(card());
  fireEvent.click(screen.getByRole("button", { name: "Bu planı karşılaştırmaya ekle" }));
  const five = { ...request, window: 5 as const };
  view.rerender(card(five, answer(5)));
  fireEvent.click(screen.getByRole("button", { name: "Bu planı karşılaştırmaya ekle" }));
  fireEvent.click(screen.getByRole("radio", { name: "Tercihim: Plan A" }));
  // A pinned plan names its Top 100 setting as the weight it is, never as a share.
  expect(
    within(screen.getByRole("region", { name: "Plan A" })).getByText(/Top 100 ağırlığı 0/),
  ).toBeInTheDocument();
  expect(view.container.textContent).not.toContain("%");
  fireEvent.change(screen.getByLabelText("Bu planı neden tercih ettim?"), {
    target: { value: "Hoca haberini bekliyorum" },
  });
  fireEvent.click(
    within(screen.getByRole("region", { name: "Plan A" })).getByRole("button", {
      name: "Ayarlarını aç",
    }),
  );
  expect(screen.getByTestId("location").textContent).toContain("window=3");
  view.unmount();
  const restored = render(card());
  expect(screen.getByRole("radio", { name: "Tercihim: Plan A" })).toBeChecked();
  expect(screen.getByLabelText("Bu planı neden tercih ettim?")).toHaveValue(
    "Hoca haberini bekliyorum",
  );
  const changed = structuredClone(squad);
  changed.payload.free_transfers++;
  restored.rerender(card(request, answer(), changed));
  expect(screen.queryByRole("region", { name: "Plan A" })).toBeNull();
});

it("keeps selection usable when storage is blocked and reports the limitation", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  render(card());
  fireEvent.click(screen.getByRole("button", { name: "Bu planı karşılaştırmaya ekle" }));
  fireEvent.click(screen.getByRole("radio", { name: "Tercihim: Plan A" }));
  expect(screen.getByRole("radio", { name: "Tercihim: Plan A" })).toBeChecked();
  expect(screen.getByText(/Sekme kaydı kullanılamıyor/)).toBeVisible();
});
