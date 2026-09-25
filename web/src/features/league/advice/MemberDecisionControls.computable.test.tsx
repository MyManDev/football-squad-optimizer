/**
 * The controls with a compute service answering: an option the publish did not solve is
 * offered wherever the service computes it, and only there. The example publish solved a
 * rival strategy at one week, no Top 100 setting and no manager's word, so everything
 * beyond that is enabled here by the capabilities alone.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdviceIndex } from "../types";
import type { AdviceCapabilities } from "./adviceCapabilities";
import { chipPath } from "./chipChoice";
import { CHIP_COPY } from "./chipCopy";
import { COMPUTE_COPY } from "./computeCopy";
import { MemberDecisionControls } from "./MemberDecisionControls";
import { TOP100_WEIGHTS } from "./top100";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const BASE = mockEntryAdviceIndex(ENTRY).payload;
const DEFAULT_RIVAL = BASE.default_rival_entry_id!;
const DECLARED = BASE.unavailable[0]!;
const OTHER_RIVAL = BASE.rival_entry_ids.find(
  (id) => id !== DEFAULT_RIVAL && id !== DECLARED.rival_entry_id,
)!;

const WHOLE_MENU: AdviceCapabilities = {
  leagueId: BASE.league_id,
  captureSnapshotId: "example-post-deadline-gw02",
  season: BASE.season,
  gameweek: BASE.gameweek,
  strategies: {
    "saf-puan": { windows: [1, 3, 5], requiresRival: false },
    "ortak-koru": { windows: [1, 3, 5], requiresRival: true },
    "fark-yarat": { windows: [1, 3, 5], requiresRival: true },
  },
  top100Weights: [...TOP100_WEIGHTS],
  managersWord: true,
};

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function query(): URLSearchParams {
  return new URLSearchParams(screen.getByTestId("location").textContent ?? "");
}

function renderControls(
  search: string,
  capabilities: AdviceCapabilities | null,
  index: EntryAdviceIndex = BASE,
) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${search}`]}>
        <MemberDecisionControls
          entryId={ENTRY}
          members={MEMBERS}
          index={index}
          capabilities={capabilities}
        />
        <Location />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

function inputs(name: string): HTMLInputElement[] {
  return Array.from(document.querySelectorAll<HTMLInputElement>(`input[name="${name}"]`));
}

function enabledValues(name: string): string[] {
  return inputs(name)
    .filter((input) => !input.disabled)
    .map((input) => input.value);
}

describe("the controls without capabilities", () => {
  it("keep a rival strategy at one week, and the unsolved switches off", () => {
    const { container } = renderControls("mode=ortak-koru", null);
    expect(enabledValues("window")).toEqual(["1"]);
    expect(enabledValues("top100")).toEqual([]);
    expect(inputs("llm")[0]!.disabled).toBe(true);
    expect(container).not.toHaveTextContent(COMPUTE_COPY.tr.controlsNote);
    expect(container).not.toHaveTextContent(COMPUTE_COPY.tr.rivalComputable);
  });
});

describe("the controls with the service's capabilities", () => {
  it.each([3, 5])(
    "retains the %s-week window and Top100 weight when switching models",
    (window) => {
      const { container } = renderControls(`mode=saf-puan&window=${window}&top100=20`, {
        ...WHOLE_MENU,
        models: ["current", "football"],
      });
      expect(container).toHaveTextContent(MESSAGES.tr.leagueMembers.windowLimits);
      fireEvent.click(inputs("prediction-model").find((input) => input.value === "football")!);
      expect(container).toHaveTextContent(
        "Her haftanın tahmini o haftanın fikstürlerinden hesaplanır",
      );
      expect(container).not.toHaveTextContent(MESSAGES.tr.leagueMembers.windowLimits);
      expect(query().get("model")).toBe("football");
      expect(query().get("window")).toBe(String(window));
      expect(query().get("top100")).toBe("20");
      expect(enabledValues("window")).toEqual(["1", "3", "5"]);
      expect(enabledValues("top100")).toEqual(TOP100_WEIGHTS.map(String));
      fireEvent.click(inputs("prediction-model").find((input) => input.value === "current")!);
      expect(container).toHaveTextContent(MESSAGES.tr.leagueMembers.windowLimits);
      expect(query().get("model")).not.toBe("football");
      expect(query().get("top100")).toBe("20");
    },
  );
  it("enables an unpublished held chip and excludes incompatible switches", () => {
    renderControls("", { ...WHOLE_MENU, chipsByEntry: { [ENTRY]: ["bboost"] } });
    expect(enabledValues("chip")).toEqual(["", "bboost"]);
    fireEvent.click(inputs("chip").find((input) => input.value === "bboost")!);
    expect(query().get("chip")).toBe("bboost");
    expect(inputs("chip").find((input) => input.value === "bboost")).toBeChecked();
    expect(enabledValues("top100")).toEqual(["0"]);
    expect(inputs("llm")[0]).toBeDisabled();
  });
  it.each([1, 3, 5])(
    "offers a named chip with Top100 over %s weeks, and never the automatic strategy",
    (window) => {
      // Audit 2026-09-25, H3: a link naming chip=auto shows no Automatic radio and
      // leaves the chip unchosen, while the capability keeps the named chips open.
      const { container } = renderControls(`mode=saf-puan&window=${window}&top100=20&chip=auto`, {
        ...WHOLE_MENU,
        chipStrategyWindows: [1, 3, 5],
        chipsByEntry: { [ENTRY]: ["3xc"] },
      });
      expect(inputs("chip").map((input) => input.value)).not.toContain("auto");
      expect(container).not.toHaveTextContent(/Otomatik strateji|Automatic strategy/);
      expect(container).toHaveTextContent(MESSAGES.tr.leagueMembers.chipStrategy.note);
      expect(enabledValues("chip")).toEqual(["", "3xc"]);
      expect(inputs("chip").find((input) => input.value === "")).toBeChecked();
      fireEvent.click(inputs("chip").find((input) => input.value === "3xc")!);
      expect(query().get("chip")).toBe("3xc");
      expect(query().get("window")).toBe(String(window));
      expect(query().get("top100")).toBe("20");
    },
  );
  it.each(["mode=saf-puan&window=3", "mode=ortak-koru&window=1"])(
    "explains why service-only chips are disabled for %s",
    (search) => {
      const { container } = renderControls(search, {
        ...WHOLE_MENU,
        chipsByEntry: { [ENTRY]: ["bboost"] },
      });
      expect(container).toHaveTextContent(CHIP_COPY.tr.onlyBaseline);
      expect(inputs("chip").find((input) => input.value === "bboost")).toBeDisabled();
    },
  );
  it("open a rival strategy's longer windows and every setting, and say how", () => {
    const { container } = renderControls("mode=ortak-koru", WHOLE_MENU);
    expect(enabledValues("window")).toEqual(["1", "3", "5"]);
    expect(enabledValues("top100")).toEqual(TOP100_WEIGHTS.map(String));
    // The word stays a one-week pure-points switch, whoever computes it.
    expect(inputs("llm")[0]!.disabled).toBe(true);
    expect(container).toHaveTextContent(COMPUTE_COPY.tr.controlsNote);
    expect(container).toHaveTextContent(COMPUTE_COPY.tr.rivalComputable);
    expect(container).toHaveTextContent(COMPUTE_COPY.tr.top100Computable);

    fireEvent.click(inputs("window")[1]!);
    expect(query().get("window")).toBe("3");
    fireEvent.click(inputs("top100")[3]!);
    expect(query().get("top100")).toBe("20");
    expect(inputs("top100")[3]!.checked).toBe(true);
  });

  it("let any member be the rival at a window nobody published, except a declared pair", () => {
    renderControls("mode=fark-yarat&window=3", WHOLE_MENU);
    const options = Array.from(document.querySelectorAll<HTMLOptionElement>("select option"));
    const byId = (id: number) => options.find((option) => option.value === String(id))!;
    expect(byId(OTHER_RIVAL).disabled).toBe(false);
    expect(byId(DEFAULT_RIVAL).disabled).toBe(false);
    fireEvent.change(document.querySelector("select")!, { target: { value: String(OTHER_RIVAL) } });
    expect(query().get("rival")).toBe(String(OTHER_RIVAL));
    expect(document.querySelector<HTMLSelectElement>("select")!.value).toBe(String(OTHER_RIVAL));
  });

  it("keep a pair the producer declared impossible off", () => {
    renderControls(`mode=${DECLARED.strategy}`, WHOLE_MENU);
    const option = Array.from(document.querySelectorAll<HTMLOptionElement>("select option")).find(
      (candidate) => candidate.value === String(DECLARED.rival_entry_id),
    )!;
    expect(option.disabled).toBe(true);
  });

  it("switch the manager's word on where only the service has it", () => {
    const { container } = renderControls("", WHOLE_MENU);
    const word = inputs("llm")[0]!;
    expect(word.disabled).toBe(false);
    expect(container).toHaveTextContent(COMPUTE_COPY.tr.wordComputable);
    fireEvent.click(word);
    expect(query().get("llm")).toBe("on");
    expect(inputs("llm")[0]!.checked).toBe(true);
  });

  it("follow the capabilities when the capture lacks a switch's input", () => {
    renderControls("", { ...WHOLE_MENU, top100Weights: [0], managersWord: false });
    expect(enabledValues("top100")).toEqual([]);
    expect(inputs("llm")[0]!.disabled).toBe(true);
    expect(enabledValues("window")).toEqual(["1", "3", "5"]);
  });

  it("offer a strategy the publish did not list when the service computes it", () => {
    const index: EntryAdviceIndex = {
      ...BASE,
      strategies: ["saf-puan"],
      windows: { "saf-puan": [1] },
      computed: [],
    };
    renderControls("", null, index);
    expect(inputs("strategy").map((input) => input.value)).toEqual(["saf-puan"]);
    cleanup();
    renderControls("", WHOLE_MENU, index);
    expect(enabledValues("strategy")).toEqual(["saf-puan", "ortak-koru", "fark-yarat"]);
    expect(enabledValues("window")).toEqual(["1", "3", "5"]);
    cleanup();
    renderControls(
      "",
      { ...WHOLE_MENU, strategies: { "saf-puan": WHOLE_MENU.strategies["saf-puan"]! } },
      index,
    );
    expect(inputs("strategy").map((input) => input.value)).toEqual(["saf-puan"]);
  });

  it("leave the chips exactly as they were: off while a switch is on, and the reverse", () => {
    const index: EntryAdviceIndex = {
      ...BASE,
      chips: {
        available: true,
        paths: { wildcard: chipPath(ENTRY, "wildcard") },
        unavailable: [],
        held: ["wildcard"],
      },
    };
    const chosen = renderControls("chip=wildcard", WHOLE_MENU, index);
    expect(inputs("chip").find((input) => input.value === "wildcard")!.checked).toBe(true);
    expect(enabledValues("top100")).toEqual(["0"]);
    expect(inputs("llm")[0]!.disabled).toBe(true);
    expect(chosen.container).toHaveTextContent(CHIP_COPY.tr.switchesOff);
    cleanup();
    renderControls("top100=20", WHOLE_MENU, index);
    expect(inputs("top100")[3]!.checked).toBe(true);
    expect(inputs("chip").find((input) => input.value === "wildcard")!.disabled).toBe(true);
  });
});
