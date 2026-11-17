import {
  MAX_MESSAGE_LENGTH,
  MAX_QUESTION_LENGTH,
  checkedDraft,
  type CatalogPlayer,
  type Clarification,
  type PlanDraft,
} from "./intent";
import { checkedPlanRevision, type PlanRevision } from "./planRevision";

export const ALTERNATIVE_COUNT = 2;

export type StartedAlternative = { kind: "priced" | "roll" } | { kind: "bank"; floor: number };

export interface PlanConfirmation {
  wildcardNotHeld: boolean;
  /** Absent until the confirmed baseline has been checked for follow-up requests. */
  followups?: (StartedAlternative | null)[];
  scenarioReplayInfeasible?: true;
  /**
   * Absent until the single prices are in. Then the preferred rules (indexes into the draft's
   * list) the plan with all preferences applies; empty when no such plan was started.
   */
  combined?: number[];
  /** Set while a request this run sent may be unanswered, so a reload can find no job id. */
  sending?: true;
}

export interface PlanSession {
  draft: PlanDraft;
  clarification?: Clarification;
  confirmation?: PlanConfirmation;
  reference?: PlanRevision;
  /**
   * Set when the squad changed under the draft. The rules then outlive the squad they were
   * written for: a reload under the new squad restores them, and nothing else.
   */
  carried?: true;
}

export interface PlanSessionContext {
  key: string;
  basis: string;
  deadline: string;
}

export function readPlanSession(context: PlanSessionContext): unknown {
  try {
    const raw = sessionStorage.getItem(context.key);
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (saved?.deadline !== context.deadline) return null;
    if (saved.basis === context.basis) return saved;
    // The plans and the reference belonged to the old squad; the rules are the member's.
    return saved.carried === true ? { draft: saved.draft } : null;
  } catch {
    return null;
  }
}

function writePlanSession(context: PlanSessionContext | null, session: PlanSession) {
  if (!context) return;
  const { key, basis, deadline } = context;
  try {
    sessionStorage.setItem(key, JSON.stringify({ basis, deadline, ...session }));
  } catch {
    // The planner remains usable without storage.
  }
}

/**
 * The page's one session writer. It keeps the confirmation of the run in memory beside the
 * saved copy, so what the page acts on and what a reload restores cannot drift apart.
 */
export interface PlanSessionStore {
  /** The confirmed run as last saved; absent while the draft has not been calculated. */
  readonly confirmation: PlanConfirmation | undefined;
  /** Saves the whole session. A session saved without a confirmation clears the run's. */
  save(session: PlanSession): void;
  /** Calls the listener after each save, so the page can render from the saved run. */
  subscribe(listener: () => void): () => void;
}

export function createPlanSessionStore(
  context: PlanSessionContext | null,
  confirmation?: PlanConfirmation,
): PlanSessionStore {
  let current = confirmation;
  const listeners = new Set<() => void>();
  return {
    get confirmation() {
      return current;
    },
    save(session) {
      current = session.confirmation;
      writePlanSession(context, session);
      for (const listener of listeners) listener();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** Saved combined rules: distinct indexes into the preferred rules, in ascending order. */
function checkedCombined(value: unknown, count: number): { combined?: number[] } {
  if (
    !Array.isArray(value) ||
    !value.every(
      (index, position) =>
        Number.isInteger(index) &&
        index >= 0 &&
        index < count &&
        (position === 0 || index > (value[position - 1] as number)),
    )
  )
    return {};
  return { combined: [...(value as number[])] };
}

export function checkedPlanSession(
  value: unknown,
  players: readonly CatalogPlayer[],
  gameweek: number,
): PlanSession | null {
  if (!value || typeof value !== "object") return null;
  const { draft, confirmation, clarification, reference } = value as Partial<PlanSession>;
  try {
    const session: PlanSession = {
      draft: checkedDraft(draft, players),
      reference: checkedPlanRevision(reference, gameweek),
    };
    if (
      typeof clarification?.message === "string" &&
      clarification.message.length <= MAX_MESSAGE_LENGTH &&
      clarification.message.trim() &&
      typeof clarification.question === "string" &&
      clarification.question.length <= MAX_QUESTION_LENGTH &&
      clarification.question.trim()
    ) {
      session.clarification = { message: clarification.message, question: clarification.question };
    }
    if (
      typeof confirmation?.wildcardNotHeld === "boolean" &&
      (confirmation.followups === undefined ||
        (Array.isArray(confirmation.followups) &&
          confirmation.followups.length <= ALTERNATIVE_COUNT))
    ) {
      session.confirmation = {
        wildcardNotHeld: confirmation.wildcardNotHeld,
        ...(session.draft.scenario && confirmation.scenarioReplayInfeasible === true
          ? { scenarioReplayInfeasible: true as const }
          : {}),
        ...(confirmation.sending === true ? { sending: true as const } : {}),
        ...checkedCombined(confirmation.combined, session.draft.soft.length),
        followups: confirmation.followups?.map((item) => {
          if (item?.kind === "priced" || item?.kind === "roll") return { kind: item.kind };
          if (
            item?.kind === "bank" &&
            Number.isInteger(item.floor) &&
            item.floor > 0 &&
            item.floor <= 10_000
          )
            return { kind: "bank", floor: item.floor };
          return null;
        }),
      };
    }
    return session;
  } catch {
    return null;
  }
}
