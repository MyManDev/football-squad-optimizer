/**
 * The duel view (#1133) on one league capture: the member's eleven beside a rival's, the
 * players both start dimmed and the others standing out, the captains and the difference in
 * the strip between them, and the rival changed with one tap. The stylesheet stacks the
 * three on a phone and times the state changes with the motion tokens.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { rivalCandidates } from "../advice/adviceSelection";
import { RivalDuel } from "./RivalDuel";

afterEach(cleanup);

const MEMBER = mockEntrySquadEnvelopes[35249001]!;
const SECOND = mockEntrySquadEnvelopes[35249002]!;
const FOURTH = mockEntrySquadEnvelopes[35249003]!;
const CANDIDATES = rivalCandidates(mockLeagueMembersEnvelope.payload.members, 35249001);

function show(props: Partial<Parameters<typeof RivalDuel>[0]> = {}, language: Language = "tr") {
  const onSelect = vi.fn();
  const view = render(
    <LanguageProvider initialLanguage={language}>
      <RivalDuel
        squad={MEMBER}
        candidates={CANDIDATES}
        selected={35249002}
        rival={SECOND}
        onSelect={onSelect}
        {...props}
      />
    </LanguageProvider>,
  );
  return { ...view, onSelect };
}

const side = (team: string) => screen.getByRole("region", { name: new RegExp(`^${team}`) });
const rows = (team: string) => within(side(team)).getAllByRole("listitem");
const named = (team: string, shared: boolean) =>
  rows(team)
    .filter((row) => row.hasAttribute("data-shared") === shared)
    .map((row) => row.children[1]!.textContent);

describe("the duel of two elevens", () => {
  it.each(["tr", "en"] as const)(
    "sets the two elevens side by side with the strip between them (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const { container } = show({}, language);
      const board = container.querySelector("[data-duel]")!;
      const [mine, strip, theirs] = [...board.children];
      expect(mine).toBe(side("North Stand Notes"));
      expect(strip!.tagName).toBe("DL");
      expect(theirs).toBe(side("Half Space"));
      expect(rows("North Stand Notes")).toHaveLength(11);
      expect(rows("Half Space")).toHaveLength(11);
      expect(within(strip as HTMLElement).getByText(copy.duelDifference)).toBeInTheDocument();
      expect(board.textContent).not.toMatch(AS_A_CHANCE);
      expect(board.textContent).not.toMatch(AS_A_CAVEAT);
    },
  );

  it("dims the players both start and marks the others, on each side", () => {
    show();
    expect(named("North Stand Notes", true)).toEqual([
      "Stone",
      "March",
      "Lane",
      "Park",
      "Hart",
      "Lake",
    ]);
    expect(named("North Stand Notes", false)).toEqual(["Vale", "Bell", "Rowe", "Cole", "Reed"]);
    expect(named("Half Space", false)).toEqual(["Cove", "Field", "Brook", "West", "Glen"]);
    for (const row of rows("Half Space").filter((item) => item.hasAttribute("data-shared")))
      expect(within(row).getByText(MESSAGES.tr.leagueMembers.duelSharedMark)).toHaveClass(
        "visually-hidden",
      );
  });

  it("shows each eleven's total, the difference, its two parts and the captains", () => {
    const copy = MESSAGES.tr.leagueMembers;
    const { container } = show();
    expect(within(side("North Stand Notes")).getByRole("heading").textContent).toContain("65,9");
    expect(within(side("Half Space")).getByRole("heading").textContent).toContain("61,1");
    const strip = container.querySelector("dl")!;
    const value = (term: string) =>
      within(strip).getByText(term).closest("div")!.querySelector("dd")!.textContent;
    expect(value(copy.duelDifference)).toContain("+4,8");
    expect(value(copy.duelFromPlayers)).toBe("+4,8");
    expect(value(copy.duelFromCaptains)).toBe("Lane · Lane 0,0");
    expect(within(strip).getByText(copy.duelShared(6))).toBeInTheDocument();
  });

  it("gives the armband's share its own line when the captains differ", () => {
    const copy = MESSAGES.en.leagueMembers;
    const { container } = show({ selected: 35249003, rival: FOURTH }, "en");
    const strip = container.querySelector("dl")!;
    const value = (term: string) =>
      within(strip).getByText(term).closest("div")!.querySelector("dd")!.textContent;
    expect(value(copy.duelDifference)).toContain("+6.6");
    expect(value(copy.duelFromPlayers)).toBe("+6.1");
    expect(value(copy.duelFromCaptains)).toBe("Lane · Cole +0.5");
    expect(within(strip).getByText(copy.duelShared(4))).toBeInTheDocument();
  });

  it("changes the rival with one tap on a button that says which one is shown", () => {
    const { onSelect } = show();
    const picker = screen.getByRole("group", { name: MESSAGES.tr.leagueMembers.duelPick });
    const buttons = within(picker).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(
      CANDIDATES.map((member) => member.team_name ?? member.manager_name ?? `#${member.entry_id}`),
    );
    expect(within(picker).getByRole("button", { name: "Half Space" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(within(picker).getByRole("button", { name: "Late Flag FC" }));
    expect(onSelect).toHaveBeenCalledWith(35249003);
  });

  it("says when the rival is being read, cannot be read, or is from another capture", () => {
    const copy = MESSAGES.tr.leagueMembers;
    show({ rival: null, issue: "loading" });
    expect(screen.getByText(copy.duelLoading)).toBeInTheDocument();
    cleanup();
    show({ rival: null, issue: "unreadable" });
    expect(screen.getByText(copy.duelUnreadable)).toBeInTheDocument();
    cleanup();
    const { container } = show({
      rival: {
        ...SECOND,
        payload: { ...SECOND.payload, source_snapshot_id: "example-post-deadline-gw03" },
      },
    });
    expect(screen.getByText(copy.duelMissing)).toBeInTheDocument();
    expect(container.querySelector("[data-duel]")).toBeNull();
  });

  it("shows only the picker until a rival is named", () => {
    const { container } = show({ selected: null, rival: null });
    expect(screen.getAllByRole("button")).toHaveLength(CANDIDATES.length);
    expect(container.querySelector("[data-duel]")).toBeNull();
  });
});

describe("the duel's stylesheet", () => {
  const css = readFileSync(join(__dirname, "RivalDuel.module.css"), "utf-8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );
  const container = css.match(/@container duel \(min-width: 640px\) \{([\s\S]*?\n)\}/)?.[1] ?? "";
  const outside = css.replace(container, "");
  const rule = (source: string, selector: string) =>
    source.match(
      new RegExp(`(?:^|\\n)${selector.replace(/[[\]]/g, "\\$&")}\\s*\\{([^}]*)\\}`),
    )?.[1] ?? "";

  it("stacks the two elevens and the strip on a phone and sets them in a row with room", () => {
    expect(rule(outside, ".board")).not.toMatch(/grid-template-columns/);
    expect(rule(container, "  .board")).toMatch(/grid-template-columns:[^;]*1fr[^;]*1fr/);
  });

  it("changes a player's state in the data time and a button's in the card time", () => {
    expect(rule(css, ".player")).toMatch(
      /background-color var\(--motion-data\) var\(--motion-ease\)/,
    );
    expect(rule(css, ".pick")).toMatch(/background-color var\(--motion-ui\) var\(--motion-ease\)/);
  });

  it("gives each rival button a thumb-sized target", () => {
    expect(rule(css, ".pick")).toMatch(/min-height: 44px/);
  });
});
