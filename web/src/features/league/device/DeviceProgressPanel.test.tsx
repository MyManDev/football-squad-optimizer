/**
 * The device solve at work in the middle of the screen: the share counts the run's stages,
 * each stage is ticked as the run passes it, and the card goes once nothing is counting.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { DeviceProgressPanel } from "./DeviceProgressPanel";
import { progressShare } from "./progress";
import type { DevicePlanPhase } from "./useDevicePlan";

afterEach(cleanup);

function show(state: DevicePlanPhase, language: "tr" | "en" = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <DeviceProgressPanel state={state} />
    </LanguageProvider>,
  );
}

const DONE = {
  phase: "done",
  envelope: {} as never,
  seconds: 0.4,
  chipTiming: null,
} as const satisfies DevicePlanPhase;

describe("the share of a device run", () => {
  it("is nothing before the inputs say how much there is, then the stages done of all", () => {
    expect(progressShare({ step: "inputs", done: 0, total: null })).toBe(0);
    expect(progressShare({ step: "plan", done: 2, total: 7 })).toBeCloseTo(2 / 7);
    expect(progressShare({ step: "chips", done: 7, total: 7 })).toBe(1);
  });
});

describe("the progress card", () => {
  it("stands over the page with the share, a progress bar and the stages, ticked as passed", () => {
    const copy = MESSAGES.tr.leagueMembers;
    show({
      phase: "solving",
      progress: { step: "plan", done: 2, total: 7, chips: { done: 0, total: 4 } },
    });
    const card = screen.getByRole("region", { name: copy.deviceSolving });
    // Drawn into the body, outside the component's own place.
    expect(card.closest("[data-device-progress]")?.parentElement).toBe(document.body);
    const bar = within(card).getByRole("progressbar", { name: copy.deviceSolving });
    expect(bar).toHaveAttribute("aria-valuenow", "29");
    expect(card).toHaveTextContent(new Intl.NumberFormat("tr", { style: "percent" }).format(2 / 7));
    const stages = within(card).getAllByRole("listitem");
    expect(stages.map((stage) => [stage.textContent, stage.dataset.stage])).toEqual([
      [copy.deviceSteps.inputs, "done"],
      [copy.deviceSteps.solver, "done"],
      [copy.deviceSteps.plan, "current"],
      [copy.deviceSteps.chips(0, 4), "waiting"],
    ]);
  });

  it("counts the chips after the plan is shown, and lists no chip stage for a run with none", () => {
    const copy = MESSAGES.en.leagueMembers;
    const view = show(
      {
        ...DONE,
        progress: { step: "chips", done: 5, total: 7, chips: { done: 2, total: 4 } },
      },
      "en",
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "71");
    expect(screen.getByText(copy.deviceSteps.chips(2, 4))).toHaveAttribute("aria-current", "step");
    view.unmount();

    show({ phase: "loading", progress: { step: "solver", done: 1, total: 3 } }, "en");
    expect(screen.getAllByRole("listitem").map((stage) => stage.textContent)).toEqual([
      copy.deviceSteps.inputs,
      copy.deviceSteps.solver,
      copy.deviceSteps.plan,
    ]);
  });

  it("is gone once nothing is counting", () => {
    for (const state of [
      { phase: "idle" },
      { phase: "loading" },
      DONE,
      { phase: "failed" },
      { phase: "refused", status: "Infeasible" },
    ] satisfies DevicePlanPhase[]) {
      const view = show(state);
      expect(document.querySelector("[data-device-progress]")).toBeNull();
      view.unmount();
    }
  });
});
