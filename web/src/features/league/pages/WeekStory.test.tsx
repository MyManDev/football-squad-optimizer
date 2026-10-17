/**
 * The week's story (#1134): transfers, captain and chip as short cards above the decision,
 * from the advice document alone. A week without a transfer or a chip shows no card for it;
 * the chip card opens on itself with the chip and its gain, and its lift is a transform in
 * the motion tokens' card time, so no other card moves and reduced motion makes it instant.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { REDUCED_MOTION_QUERY } from "../../../design/motion";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { CHIP_COPY } from "../advice/chipCopy";
import type { AdvicePlayer, EntryAdvice } from "../types";
import { STORY_ANCHORS } from "./storyPlan";
import { WeekStory } from "./WeekStory";

afterEach(() => {
  cleanup();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

const ENTRY = 35249001;

function player(id: number, short: string): AdvicePlayer {
  return { player_id: id, name: `Player ${short}`, short_name: short, position: "MID", team: "X" };
}

const PALMER = player(1, "Palmer");
const FERNANDES = player(2, "Fernandes");
const JESUS = player(3, "Jesus");
const BROBBEY = player(4, "Brobbey");
const HAALAND = player(5, "Haaland");

/** A solved plan: two moves, Haaland the captain, and whatever the case adds. */
function plan(patch: Partial<EntryAdvice> = {}): EntryAdvice {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
  return {
    ...base,
    moves: [
      {
        move_id: "m1",
        player_out: PALMER,
        player_in: FERNANDES,
        expected_points_delta: 2.4,
        reason_code: "points_gain",
      },
      {
        move_id: "m2",
        player_out: JESUS,
        player_in: BROBBEY,
        expected_points_delta: 0.6,
        reason_code: "points_gain",
      },
    ],
    solver_status: "OPTIMAL",
    captain: HAALAND,
    vice_captain: FERNANDES,
    chip: null,
    ...patch,
  };
}

function show(view: EntryAdvice, language: Language = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <WeekStory view={view} />
    </LanguageProvider>,
  );
}

const cards = () => screen.getAllByRole("listitem");
const kinds = () => cards().map((card) => card.getAttribute("data-story"));

describe("the week's story", () => {
  it.each(["tr", "en"] as const)("tells a three-decision week as three cards (%s)", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    show(
      plan({ chip: "3xc", chip_choice: { chip: "3xc", gain_vs_no_chip: 6.4, basis: "x" } }),
      language,
    );
    const story = screen.getByRole("navigation", { name: copy.storyTitle });
    expect(kinds()).toEqual(["transfers", "captain", "chip"]);
    const [transfers, captain, chip] = cards();
    expect(within(transfers!).getByRole("link")).toHaveAttribute(
      "href",
      `#${STORY_ANCHORS.transfers}`,
    );
    expect(within(transfers!).getByText(copy.storyMoves(2))).toBeInTheDocument();
    expect(within(transfers!).getByText("Palmer → Fernandes, Jesus → Brobbey")).toBeInTheDocument();
    expect(within(captain!).getByRole("link")).toHaveAttribute("href", `#${STORY_ANCHORS.captain}`);
    expect(within(captain!).getByText("Haaland")).toBeInTheDocument();
    expect(within(chip!).getByText(copy.chipNames["3xc"]!)).toBeInTheDocument();
    expect(story.textContent).not.toMatch(AS_A_CHANCE);
    expect(story.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("shows no chip card on a week whose document names no chip", () => {
    show(plan());
    expect(kinds()).toEqual(["transfers", "captain"]);
  });

  it("shows no transfer card on a week without a move, and nothing without a solved plan", () => {
    show(plan({ moves: [] }));
    expect(kinds()).toEqual(["captain"]);
    cleanup();
    const { container } = show(plan({ solver_status: "UNKNOWN" as EntryAdvice["solver_status"] }));
    expect(container.innerHTML).toBe("");
  });

  it("opens the chip card on itself with the chip week's gain and a link to its detail", () => {
    const copy = MESSAGES.tr.leagueMembers;
    show(plan({ chip: "3xc", chip_choice: { chip: "3xc", gain_vs_no_chip: 6.4, basis: "x" } }));
    const chip = cards()[2]!;
    const button = within(chip).getByRole("button");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(within(chip).queryByText(copy.storyChipPlay)).toBeNull();
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(chip).toHaveAttribute("data-open");
    expect(within(chip).getByText(copy.storyChipPlay)).toBeInTheDocument();
    expect(within(chip).getByText(CHIP_COPY.tr.gain("+6,4"))).toBeInTheDocument();
    expect(within(chip).getByRole("link", { name: copy.storyDetail })).toHaveAttribute(
      "href",
      `#${STORY_ANCHORS.chip}`,
    );
    fireEvent.click(button);
    expect(chip).not.toHaveAttribute("data-open");
  });

  it("opens at once under reduced motion: the state changes with no wait", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        media: query,
        matches: query === REDUCED_MOTION_QUERY,
        addEventListener() {},
        removeEventListener() {},
      }),
    });
    show(plan({ chip: "bboost", chip_choice: { chip: "bboost", gain_vs_no_chip: 2, basis: "x" } }));
    const chip = cards()[2]!;
    fireEvent.click(within(chip).getByRole("button"));
    expect(chip).toHaveAttribute("data-open");
    expect(within(chip).getByText(MESSAGES.tr.leagueMembers.storyChipPlay)).toBeInTheDocument();
  });
});

describe("the chip card's lift", () => {
  const css = readFileSync(join(__dirname, "WeekStory.module.css"), "utf-8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );
  const rule = (selector: string) =>
    css.match(new RegExp(`${selector.replace(/[[\]]/g, "\\$&")}\\s*\\{([^}]*)\\}`))?.[1] ?? "";

  it("is a transform and a shadow only, so no other card moves", () => {
    const declared = rule(".card[data-open]")
      .split(";")
      .map((line) => line.split(":")[0]!.trim())
      .filter(Boolean);
    expect(declared.sort()).toEqual(["box-shadow", "transform"]);
  });

  it("takes the card time of the motion tokens", () => {
    expect(rule(".card")).toMatch(/transform var\(--motion-ui\) var\(--motion-ease\)/);
  });
});
