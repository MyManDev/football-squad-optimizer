import { afterEach, describe, expect, it, vi } from "vitest";

import { readReply } from "../../../testSupport/intentReply";
import { EMPTY_DRAFT, MAX_MESSAGE_LENGTH, MAX_QUESTION_LENGTH } from "./intent";
import {
  checkedPlanSession,
  createPlanSessionMemory,
  createPlanSessionStore,
  readPlanSession,
} from "./planSession";

const OWNED = [
  { id: 1, name: "Held One", team: "Arsenal" },
  { id: 2, name: "Held Two", team: "Brighton" },
];
const ROSTER = [...OWNED, { id: 3, name: "Outside", team: "Chelsea" }];
const GAMEWEEK = 5;

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("createPlanSessionStore", () => {
  const context = {
    key: "squadopt.llmopt:test",
    basis: "basis",
    season: "2029-30",
    gameweek: GAMEWEEK,
    deadline: "2030-01-01T00:00:00Z",
  };
  const draft = { hard: [{ kind: "no_hits" as const }], soft: [] };

  it("saves the whole session and keeps the run's confirmation beside it", () => {
    const store = createPlanSessionStore(context);
    expect(store.confirmation).toBeUndefined();
    const confirmation = { wildcardNotHeld: false, sending: true as const };
    store.save({ draft, confirmation });
    expect(store.confirmation).toEqual(confirmation);
    const { key: _key, ...metadata } = context;
    expect(readPlanSession(context)).toEqual({ ...metadata, draft, confirmation });
  });

  it("drops the confirmation when a session is saved without one", () => {
    const store = createPlanSessionStore(context, { wildcardNotHeld: true });
    expect(store.confirmation).toEqual({ wildcardNotHeld: true });
    store.save({ draft });
    expect(store.confirmation).toBeUndefined();
    expect(readPlanSession(context)).not.toHaveProperty("confirmation");
  });

  it("tells its listeners after each save until they leave", () => {
    const store = createPlanSessionStore(context);
    const listener = vi.fn();
    const leave = store.subscribe(listener);
    store.save({ draft, confirmation: { wildcardNotHeld: false, combined: [0, 1] } });
    expect(listener).toHaveBeenCalledTimes(1);
    leave();
    store.save({ draft });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("restores the combined rules only as distinct ascending indexes into the preferred rules", () => {
    const soft = [{ kind: "no_hits" }, { kind: "hold_transfers" }, { kind: "save_chips" }];
    const restore = (combined: unknown) =>
      checkedPlanSession(
        { draft: { hard: [], soft }, confirmation: { wildcardNotHeld: false, combined } },
        ROSTER,
        GAMEWEEK,
      )?.confirmation;
    expect(restore([0, 2])).toMatchObject({ combined: [0, 2] });
    expect(restore([])).toMatchObject({ combined: [] });
    for (const odd of [[2, 0], [0, 0], [3], [-1], [0.5], "0", null])
      expect(restore(odd)).not.toHaveProperty("combined");
  });

  it("reads nothing back for another deadline", () => {
    createPlanSessionStore(context).save({ draft });
    expect(readPlanSession({ ...context, deadline: "2031-01-01T00:00:00Z" })).toBeNull();
  });

  it("reads nothing back for another season or gameweek with the same deadline", () => {
    createPlanSessionStore(context).save({ draft });
    expect(readPlanSession({ ...context, season: "2030-31" })).toBeNull();
    expect(readPlanSession({ ...context, gameweek: GAMEWEEK + 1 })).toBeNull();
  });

  it("keeps the latest full session in the open page when storage becomes unavailable", () => {
    const memory = createPlanSessionMemory();
    const store = createPlanSessionStore(context, undefined, memory);
    store.save({ draft });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Full", "QuotaExceededError");
    });
    const latest = {
      draft: { hard: [{ kind: "hold_transfers" as const }], soft: [] },
      confirmation: { wildcardNotHeld: false, sending: true as const },
      reference: { gameweek: GAMEWEEK, window: 1 as const, net: null, weeks: [] },
      clarification: { message: "A prior instruction", question: "Which player?" },
    };
    store.save(latest);
    expect(memory.read(context)).toEqual(latest);
    expect(memory.read({ ...context, basis: "new-squad" })).toEqual({ draft: latest.draft });
    vi.restoreAllMocks();
  });

  it("carries an undated draft into its stated deadline without a run or reference", () => {
    const memory = createPlanSessionMemory();
    memory.save(
      { ...context, deadline: null },
      { draft, confirmation: { wildcardNotHeld: false } },
    );
    expect(sessionStorage.length).toBe(0);
    expect(memory.read(context)).toEqual({ draft });
    expect(readPlanSession(context)).toBeNull();
    createPlanSessionStore(context, undefined, memory).save({ draft });
    expect(readPlanSession(context)).toMatchObject({ draft, deadline: context.deadline });
  });

  it("isolates live drafts by identity and week, and resets for another stated deadline", () => {
    const memory = createPlanSessionMemory();
    memory.save({ ...context, deadline: null }, { draft });
    for (const other of [
      { key: "another-origin" },
      { key: "another-forwarded-mode" },
      { key: "another-league" },
      { key: "another-entry" },
      { season: "2030-31" },
      { gameweek: GAMEWEEK + 1 },
    ])
      expect(memory.read({ ...context, ...other })).toBeNull();
    memory.save(context, { draft });
    expect(memory.read({ ...context, deadline: "2030-01-02T00:00:00Z" })).toBeNull();
  });

  it("carries the rules, and only the rules, to a new squad when the old one changed under them", () => {
    const confirmation = { wildcardNotHeld: false };
    createPlanSessionStore(context).save({
      draft,
      confirmation,
      clarification: { message: "A prior instruction", question: "Which player?" },
      reference: { gameweek: GAMEWEEK, window: 1, net: null, weeks: [] },
    });
    expect(readPlanSession({ ...context, basis: "other" })).toEqual({ draft });
    expect(
      readPlanSession({ ...context, basis: "other", deadline: "2031-01-01T00:00:00Z" }),
    ).toBeNull();
  });

  it("keeps working without a context or without storage", () => {
    const detached = createPlanSessionStore(null);
    detached.save({ draft, confirmation: { wildcardNotHeld: false } });
    expect(detached.confirmation).toEqual({ wildcardNotHeld: false });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    const store = createPlanSessionStore(context);
    expect(() => store.save({ draft })).not.toThrow();
    vi.restoreAllMocks();
  });
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
  const ask = (question: string) =>
    readReply(new Response(JSON.stringify({ status: "clarification", message: question })), ROSTER);

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
