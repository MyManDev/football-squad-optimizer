import { afterEach, describe, expect, it, vi } from "vitest";

import { EMPTY_DRAFT, MAX_MESSAGE_LENGTH, MAX_QUESTION_LENGTH, readIntent } from "./intent";
import { checkedPlanSession } from "./planSession";

const OWNED = [
  { id: 1, name: "Held One", team: "Arsenal" },
  { id: 2, name: "Held Two", team: "Brighton" },
];
const ROSTER = [...OWNED, { id: 3, name: "Outside", team: "Chelsea" }];
const GAMEWEEK = 5;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("checkedPlanSession", () => {
  const outsider = { draft: { hard: [{ kind: "include_player", player_id: 3 }], soft: [] } };

  it("restores a draft that names a player outside the squad once the roster is read", () => {
    expect(checkedPlanSession(outsider, ROSTER, GAMEWEEK)?.draft).toEqual(outsider.draft);
  });

  it("cannot check that draft against the squad alone, so the page holds it for the roster", () => {
    expect(checkedPlanSession(outsider, OWNED, GAMEWEEK)).toBeNull();
  });

  it("restores a draft of squad players against the squad alone", () => {
    const squadOnly = { draft: { hard: [{ kind: "keep_player", player_id: 1 }], soft: [] } };
    expect(checkedPlanSession(squadOnly, OWNED, GAMEWEEK)?.draft).toEqual(squadOnly.draft);
  });

  it("restores a clarification at the full message and question lengths", () => {
    const clarification = {
      message: "m".repeat(MAX_MESSAGE_LENGTH),
      question: "q".repeat(MAX_QUESTION_LENGTH),
    };
    const session = checkedPlanSession({ draft: EMPTY_DRAFT, clarification }, ROSTER, GAMEWEEK);
    expect(session?.clarification).toEqual(clarification);
  });

  it("restores a run confirmed just before the reload, before any follow-up started", () => {
    const session = checkedPlanSession(
      { draft: EMPTY_DRAFT, confirmation: { wildcardNotHeld: false, sending: true } },
      ROSTER,
      GAMEWEEK,
    );
    expect(session?.confirmation).toEqual({
      wildcardNotHeld: false,
      sending: true,
      followups: undefined,
    });
    const odd = { draft: EMPTY_DRAFT, confirmation: { wildcardNotHeld: false, sending: "yes" } };
    expect(checkedPlanSession(odd, ROSTER, GAMEWEEK)?.confirmation).not.toHaveProperty("sending");
  });
});

describe("a clarification question", () => {
  const ask = (question: string) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ status: "clarification", message: question })),
        ),
    );
    return readIntent(
      "https://advice.example",
      "Buy a striker.",
      "en",
      EMPTY_DRAFT,
      ROSTER,
      new AbortController().signal,
    );
  };

  it("is read up to the length the session restores", async () => {
    const question = "q".repeat(MAX_QUESTION_LENGTH);
    await expect(ask(` ${question} `)).resolves.toEqual({
      status: "clarification",
      message: question,
    });
  });

  it("is refused past that length, so a saved question is never dropped on restore", async () => {
    await expect(ask("q".repeat(MAX_QUESTION_LENGTH + 1))).rejects.toThrow("Invalid response");
  });
});
