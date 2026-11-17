import { cleanup, render, screen } from "@testing-library/react";
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
