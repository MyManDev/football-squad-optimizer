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
  /** Set while a request this run sent may be unanswered, so a reload can find no job id. */
  sending?: true;
}

export interface PlanSession {
  draft: PlanDraft;
  clarification?: Clarification;
  confirmation?: PlanConfirmation;
  reference?: PlanRevision;
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
}

export function createPlanSessionStore(
  context: PlanSessionContext | null,
  confirmation?: PlanConfirmation,
): PlanSessionStore {
  let current = confirmation;
  return {
    get confirmation() {
      return current;
    },
    save(session) {
      current = session.confirmation;
      writePlanSession(context, session);
    },
  };
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
