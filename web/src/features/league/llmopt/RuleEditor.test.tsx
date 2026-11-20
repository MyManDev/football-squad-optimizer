import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Language } from "../../../i18n/messages";
import { LLMOPT_COPY, ruleLabel } from "./copy";
import type { CatalogPlayer, PlanDraft } from "./intent";
import { RuleEditor } from "./RuleEditor";

const PLAYERS: CatalogPlayer[] = [
  { id: 1, name: "First", team: "Arsenal", held: true },
  { id: 2, name: "Second", team: "Arsenal" },
  { id: 3, name: "Third", team: "Brighton" },
];

afterEach(cleanup);

it.each(["en", "tr"] as const)(
  "distinguishes an unset priority from normal when editing or adding a preference in %s",
  async (language) => {
    const copy = LLMOPT_COPY[language];
    const change = vi.fn();
    render(
      <RuleEditor
        draft={{ hard: [], soft: [{ kind: "no_hits" }] }}
        players={PLAYERS}
        copy={copy}
        priorities
        disabled={false}
        change={change}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText(copy.strength), "soft");
    const saved = screen.getByRole("combobox", {
      name: `${copy.priority} · ${copy.rules.no_hits}`,
    });
    const added = screen.getByRole("combobox", { name: copy.priority });
    for (const select of [saved, added]) {
      expect(select).toHaveValue("");
      expect(within(select).getByRole("option", { name: copy.noPriority })).toHaveValue("");
      expect(within(select).getByRole("option", { name: copy.priorityLevels[2] })).toHaveValue("2");
    }
    await userEvent.selectOptions(saved, "2");
    expect(change).toHaveBeenCalledWith({ hard: [], soft: [{ kind: "no_hits", priority: 2 }] });
  },
);

describe("the club rule reads as an exact count", () => {
  it.each([
    ["en", "Exact number of players", "Arsenal · Final squad · exactly 2"],
    ["tr", "Tam olarak kaç oyuncu", "Arsenal · Son kadro · tam olarak 2"],
  ] as const)("in %s", async (language: Language, field, listed) => {
    const copy = LLMOPT_COPY[language];
    const change = vi.fn();
    const draft: PlanDraft = {
      hard: [{ kind: "club_count", club: "Arsenal", count: 2 }],
      soft: [],
    };
    render(
      <RuleEditor draft={draft} players={PLAYERS} copy={copy} disabled={false} change={change} />,
    );

    expect(screen.getByText(listed, { exact: true })).toBeVisible();
    expect(ruleLabel(draft.hard[0]!, PLAYERS, copy)).toBe(listed);

    await userEvent.selectOptions(screen.getByLabelText(copy.rule), "club_count");
    expect(screen.getByRole("option", { name: copy.rules.club_count })).toBeInTheDocument();
    expect(copy.rules.club_count).toMatch(language === "en" ? /\bExact\b/ : /\btam olarak\b/);
    await userEvent.selectOptions(screen.getByLabelText(copy.club), "Brighton");
    await userEvent.selectOptions(screen.getByLabelText(field), "3");
    await userEvent.click(screen.getByRole("button", { name: copy.add }));

    expect(change).toHaveBeenCalledWith({
      hard: [
        { kind: "club_count", club: "Arsenal", count: 2 },
        { kind: "club_count", club: "Brighton", count: 3 },
      ],
      soft: [],
    });
  });
});

describe("a preferred rule", () => {
  const copy = LLMOPT_COPY.en;

  function editor(draft: PlanDraft, change = vi.fn()) {
    render(
      <RuleEditor draft={draft} players={PLAYERS} copy={copy} disabled={false} change={change} />,
    );
    return change;
  }

  it("carries its points limit in tenths", async () => {
    const change = editor({ hard: [], soft: [] });
    await userEvent.selectOptions(screen.getByLabelText(copy.rule), "include_player");
    await userEvent.selectOptions(screen.getByLabelText(copy.player), "2");
    await userEvent.selectOptions(screen.getByLabelText(copy.strength), "soft");
    await userEvent.type(screen.getByLabelText(copy.preferenceLimit), "1,5");
    await userEvent.click(screen.getByRole("button", { name: copy.add }));

    expect(change).toHaveBeenCalledWith({
      hard: [],
      soft: [{ kind: "include_player", player_id: 2, max_cost_tenths: 15 }],
    });
  });

  it("replaces the same rule held as required, and is listed with its limit", async () => {
    const rule = { kind: "include_player", player_id: 2 } as const;
    const change = editor({ hard: [rule], soft: [{ kind: "no_hits", max_cost_tenths: 10 }] });
    expect(
      screen.getByRole("button", {
        name: `${copy.remove} · ${copy.rules.no_hits} · ${copy.preferenceLimitLabel(10)}`,
      }),
    ).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText(copy.rule), "include_player");
    await userEvent.selectOptions(screen.getByLabelText(copy.player), "2");
    await userEvent.selectOptions(screen.getByLabelText(copy.strength), "soft");
    await userEvent.click(screen.getByRole("button", { name: copy.add }));

    expect(change).toHaveBeenCalledWith({
      hard: [],
      soft: [{ kind: "no_hits", max_cost_tenths: 10 }, rule],
    });
  });

  it("is removed on its own", async () => {
    const change = editor({
      hard: [{ kind: "no_hits" }],
      soft: [{ kind: "hold_transfers" }, { kind: "save_chips" }],
    });
    await userEvent.click(
      screen.getByRole("button", { name: `${copy.remove} · ${copy.rules.hold_transfers}` }),
    );
    expect(change).toHaveBeenCalledWith({
      hard: [{ kind: "no_hits" }],
      soft: [{ kind: "save_chips" }],
    });
  });
});
