import type { Language } from "../../../i18n/messages";
import type { PlanWeekNumber } from "../advice/decisionPreferences";
import { readIntent, type CatalogPlayer, type Clarification, type PlanDraft } from "./intent";

/** What the page asks a model to read: the member's message and the draft it changes. */
export interface IntentRequest {
  message: string;
  locale: Language;
  draft: PlanDraft;
  players: CatalogPlayer[];
  clarification?: Clarification;
  referenceWeeks?: readonly PlanWeekNumber[];
  referenceCaptains?: readonly { week: PlanWeekNumber; player_id: number }[];
}

/** A checked answer: a new draft, or one question back to the member. */
export type IntentResult =
  { status: "draft"; draft: PlanDraft } | { status: "clarification"; message: string };

/**
 * Where the page's chat is read. Each source returns a draft already checked against the
 * players it was given. A named refusal rejects with an `IntentError`; any other rejection
 * reads on the page as the chat being unavailable.
 */
export interface IntentSource {
  interpret(request: IntentRequest, signal: AbortSignal): Promise<IntentResult>;
}

/** The site's own intent service, `POST /api/v1/llmopt/intent`. */
export function serverIntentSource(origin: string): IntentSource {
  return {
    interpret: (request, signal) =>
      readIntent(
        origin,
        request.message,
        request.locale,
        request.draft,
        request.players,
        signal,
        request.clarification,
        request.referenceWeeks,
        request.referenceCaptains,
      ),
  };
}
