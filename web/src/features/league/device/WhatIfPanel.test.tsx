/**
 * The what-if mode (#1132) on the synthetic device capture, member 1, with the device's
 * own solver answering in process: the advised fifteen reads as the plan, one swap moves
 * the bank, the points and the difference at once, a rule the fifteen breaks is said in
 * words, the reset returns to the advice, and after the table is read once every change
 * is answered with no further read.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { withLeague } from "../../../testSupport/league";
import { LeagueDataMissing } from "../dataErrors";
import type { EntrySquad, LeagueViewEnvelope } from "../types";
import type { LpSolver } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";
import type { WhatIfDependencies, WhatIfSolver } from "./useWhatIf";
import { whatIfDocument, whatIfValues } from "./whatIf";
import type { WhatIfReply, WhatIfRequest } from "./whatIf.worker";
import { WhatIfPanel } from "./WhatIfPanel";

afterEach(cleanup);

const require = createRequire(import.meta.url);
let highs: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  highs = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const COPY = MESSAGES.tr.leagueMembers;
const document = fixture.document as unknown as DevicePlanDocument;
const member = fixture.members[0]!;
const ADVISED = member.reference.squad;
const SQUAD: EntrySquad = {
  ...mockEntrySquadEnvelopes[35249001]!.payload,
  source_snapshot_id: document.source_snapshot_id,
  device_plan: member.entry as unknown as DevicePlanEntry,
};

/** The worker, answered in process with the device's own solver. */
class InProcessSolver implements WhatIfSolver {
  onmessage: ((event: MessageEvent<WhatIfReply>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  readonly asked: WhatIfRequest[] = [];
  postMessage(request: WhatIfRequest): void {
    this.asked.push(request);
    const reply: WhatIfReply = {
      id: request.id,
      kind: "values",
      values: whatIfValues(highs, request.document, request.squads),
    };
    queueMicrotask(() => this.onmessage?.({ data: reply } as MessageEvent<WhatIfReply>));
  }
  terminate(): void {}
}

function envelope(payload: DevicePlanDocument): LeagueViewEnvelope<DevicePlanDocument> {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-03T00:00:00Z",
    source_kind: "live",
    payload,
  };
}

function show(dependencies: Partial<WhatIfDependencies> = {}, squad: EntrySquad = SQUAD) {
  const worker = new InProcessSolver();
  const loadDocument = vi.fn(async () => envelope(document));
  const view = render(
    <LanguageProvider initialLanguage="tr">
      {withLeague(
        <WhatIfPanel
          squad={squad}
          advised={ADVISED}
          dependencies={{ loadDocument, createSolver: () => worker, ...dependencies }}
        />,
      )}
    </LanguageProvider>,
  );
  return { ...view, worker, loadDocument };
}

/** The account's figure under its term, once the solver has answered. */
const figure = (term: string) =>
  screen.getByText(term, { selector: "dt" }).parentElement!.querySelector("dd")!.textContent;

async function started() {
  const shown = show();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: COPY.whatIfStart }));
  });
  await screen.findByText("74,39", { exact: false });
  return shown;
}

const remove = (name: string) =>
  fireEvent.click(screen.getByRole("button", { name: COPY.whatIfRemoveLabel(name) }));
const add = (id: number) =>
  fireEvent.change(screen.getByLabelText(COPY.whatIfAdd), { target: { value: String(id) } });

async function settled() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("the advised fifteen", () => {
  it("reads as the device's plan: its bank, points, one transfer and no difference", async () => {
    const { container } = await started();
    expect(figure(COPY.whatIfBank)).toBe("0,7m");
    expect(figure(COPY.whatIfPoints)).toContain("74,39");
    expect(figure(COPY.whatIfTransfers)).toBe("1");
    expect(figure(COPY.whatIfDifference)).toContain("0,0");
    expect(screen.getByRole("button", { name: COPY.whatIfReset })).toBeDisabled();
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.textContent).not.toMatch(AS_A_CAVEAT);
  });
});

describe("one swap", () => {
  it("taking the transfer back moves the bank, the points and the difference at once", async () => {
    await started();
    remove("160");
    add(152);
    await settled();
    expect(figure(COPY.whatIfBank)).toBe("0,0m");
    expect(figure(COPY.whatIfPoints)).toContain("66,38");
    expect(figure(COPY.whatIfTransfers)).toBe("0");
    // The plan's gain over holding, turned: 66.38 against 74.39.
    expect(figure(COPY.whatIfDifference)).toContain("−8,0");
    const row = screen.getByRole("button", { name: COPY.whatIfRemoveLabel("152") }).closest("li")!;
    expect(row).toHaveAttribute("data-changed");
  });
});

describe("a rule the fifteen breaks", () => {
  it("is said in words, and the difference is taken net of the hit it costs", async () => {
    await started();
    remove("145");
    add(147);
    await settled();
    expect(screen.getByText(COPY.whatIfBreaks.club("Club 3", 4, 3))).toBeInTheDocument();
    expect(figure(COPY.whatIfTransfers)).toBe(`2 · ${COPY.whatIfHit("−4")}`);
    const tried = ADVISED.map((id) => (id === 145 ? 147 : id));
    const [advised, value] = whatIfValues(highs, whatIfDocument(document), [ADVISED, tried]);
    const expected = value! - 4 - advised!;
    expect(figure(COPY.whatIfDifference)).toContain(
      `${expected < 0 ? "−" : "+"}${Math.abs(expected).toFixed(1).replace(".", ",")}`,
    );
  });

  it("a removed player leaves the squad short, said for the squad and the position", async () => {
    await started();
    remove("148");
    await settled();
    expect(screen.getByText(COPY.whatIfBreaks.size(14, 15))).toBeInTheDocument();
    expect(
      screen.getByText(COPY.whatIfBreaks.position(MESSAGES.tr.positions.MID, 4, 5)),
    ).toBeInTheDocument();
  });

  it("a purchase past the bank is said with what it is short", async () => {
    await started();
    remove("129");
    add(134);
    await settled();
    expect(screen.getByText(COPY.whatIfBreaks.budget("6,2m"))).toBeInTheDocument();
    expect(figure(COPY.whatIfBank)).toBe("-6,2m");
  });
});

describe("the reset", () => {
  it("returns to the advised fifteen and its numbers", async () => {
    await started();
    remove("145");
    add(147);
    await settled();
    fireEvent.click(screen.getByRole("button", { name: COPY.whatIfReset }));
    await settled();
    expect(figure(COPY.whatIfTransfers)).toBe("1");
    expect(figure(COPY.whatIfDifference)).toContain("0,0");
    expect(screen.queryByText(COPY.whatIfBreaks.club("Club 3", 4, 3))).toBeNull();
    expect(screen.getByRole("button", { name: COPY.whatIfReset })).toBeDisabled();
  });
});

describe("on the device", () => {
  it("reads the table once and answers every change after it with no read", async () => {
    const { loadDocument, worker } = await started();
    remove("160");
    add(152);
    remove("145");
    await settled();
    expect(loadDocument).toHaveBeenCalledTimes(1);
    expect(worker.asked.length).toBeGreaterThanOrEqual(3);
  });

  it("keeps the last points, marked as being read, until the solver answers", async () => {
    const worker = new InProcessSolver();
    const held: Array<() => void> = [];
    const slow: WhatIfSolver = {
      onmessage: null,
      onerror: null,
      postMessage(request) {
        worker.onmessage = (event) => slow.onmessage?.(event);
        held.push(() => worker.postMessage(request));
      },
      terminate() {},
    };
    show({ createSolver: () => slow });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: COPY.whatIfStart }));
    });
    await act(async () => held.shift()!());
    await screen.findByText("74,39", { exact: false });
    remove("160");
    const account = screen.getByText(COPY.whatIfPoints, { selector: "dt" }).closest("dl")!;
    expect(account).toHaveAttribute("aria-busy", "true");
    expect(figure(COPY.whatIfPoints)).toContain("74,39");
    await act(async () => held.shift()!());
    expect(account).toHaveAttribute("aria-busy", "false");
  });
});

describe("what the mode says before it can start", () => {
  it.each([
    [
      "an unpublished table",
      () => Promise.reject(new LeagueDataMissing("device-plan.json")),
      COPY.whatIfUnpublished,
    ],
    ["an unreadable table", () => Promise.reject(new Error("broken")), COPY.whatIfFailed],
    [
      "a table of another capture",
      async () => envelope({ ...document, source_snapshot_id: "another" }),
      COPY.whatIfOtherCapture,
    ],
    [
      "a table without one of the advised players",
      async () =>
        envelope({ ...document, players: document.players.filter((player) => player.id !== 160) }),
      COPY.whatIfOtherCapture,
    ],
  ])("says so for %s", async (_, loadDocument, said) => {
    show({ loadDocument });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: COPY.whatIfStart }));
    });
    expect(await screen.findByText(said)).toBeInTheDocument();
  });
});

describe("the panel's stylesheet", () => {
  const css = readFileSync(join(__dirname, "WhatIfPanel.module.css"), "utf-8");
  it("changes a row's state in the card time and gives each button a thumb-sized target", () => {
    expect(css).toMatch(
      /\.player \{[^}]*transition: background-color var\(--motion-ui\) var\(--motion-ease\)/,
    );
    for (const selector of [".action", ".remove"])
      expect(css).toMatch(new RegExp(`\\${selector} \\{[^}]*min-height: 44px`));
  });
});

it("lists the fifteen by position, each row with its own remove button", async () => {
  await started();
  const groups = screen.getAllByRole("list").filter((list) => list.tagName === "OL");
  expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
    MESSAGES.tr.positions.GK,
    MESSAGES.tr.positions.DEF,
    MESSAGES.tr.positions.MID,
    MESSAGES.tr.positions.FWD,
  ]);
  expect(groups.flatMap((group) => within(group).getAllByRole("button"))).toHaveLength(15);
});
