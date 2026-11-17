import { withRequestDeadline } from "../../../data/request";
import type { Language } from "../../../i18n/messages";
import type { PlanWeekNumber } from "../advice/decisionPreferences";
import {
  intentAnswer,
  intentBody,
  intentError,
  readIntent,
  type CatalogPlayer,
  type Clarification,
  type PlanDraft,
} from "./intent";
import { withOwnKey, type ProviderCredential } from "./ownKey";
import { callProvider, checkedProviderCall } from "./providers";

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

/** How a source reaches the held key: `withOwnKey`, or a stand-in in a test. */
export type KeyedCall = <T>(call: (credential: ProviderCredential) => Promise<T>) => Promise<T>;

/** A JSON POST to one of the site's keyless routes. It carries no key and no credential. */
async function postKeyless(url: string, body: unknown, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw await intentError(response);
  return response.json();
}

/**
 * The member's own model (ADR 0017). The site's `/prompt` returns the call, this browser
 * sends it to the member's provider with the member's key, and the site's `/check` validates
 * the reply. The key goes only to the provider's host.
 */
export function ownKeyIntentSource(origin: string, keyed: KeyedCall = withOwnKey): IntentSource {
  return {
    interpret: (request, signal) =>
      withRequestDeadline(
        async (signal) => {
          const body = intentBody(
            request.message,
            request.locale,
            request.draft,
            request.players,
            request.clarification,
            request.referenceWeeks,
            request.referenceCaptains,
          );
          const call = checkedProviderCall(
            await postKeyless(`${origin}/api/v1/llmopt/prompt`, body, signal),
          );
          const reply = await keyed((credential) => callProvider(credential, call, signal));
          const answer = await postKeyless(
            `${origin}/api/v1/llmopt/check`,
            { request: body, reply },
            signal,
          );
          return intentAnswer(answer, request.players);
        },
        { signal, timeoutMs: 120_000 },
      ),
  };
}
