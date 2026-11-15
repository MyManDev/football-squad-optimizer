import {
  MAX_MESSAGE_LENGTH,
  MAX_QUESTION_LENGTH,
  checkedDraft,
  type CatalogPlayer,
  type Clarification,
  type PlanDraft,
} from "./intent";

export const ALTERNATIVE_COUNT = 2;

export type StartedAlternative = { kind: "priced" | "roll" } | { kind: "bank"; floor: number };

export interface PlanConfirmation {
  wildcardNotHeld: boolean;
  /** Absent until the confirmed baseline has been checked for follow-up requests. */
  followups?: (StartedAlternative | null)[];
}

interface PlanSession {
  draft: PlanDraft;
  clarification?: Clarification;
  confirmation?: PlanConfirmation;
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
    return saved?.basis === context.basis && saved?.deadline === context.deadline ? saved : null;
  } catch {
    return null;
  }
}

export function writePlanSession(context: PlanSessionContext | null, session: PlanSession) {
  if (!context) return;
  const { key, basis, deadline } = context;
  try {
    sessionStorage.setItem(key, JSON.stringify({ basis, deadline, ...session }));
  } catch {
    // The planner remains usable without storage.
  }
}

export function checkedPlanSession(
  value: unknown,
  players: readonly CatalogPlayer[],
): PlanSession | null {
  if (!value || typeof value !== "object") return null;
  const { draft, confirmation, clarification } = value as Partial<PlanSession>;
  try {
    const session: PlanSession = { draft: checkedDraft(draft, players) };
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
