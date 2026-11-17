import { useSyncExternalStore } from "react";

/**
 * The member's own model key (ADR 0017). It is held in this module's memory for this tab and
 * nowhere else: no storage, no cookie, no address, no saved session, no usage record and no
 * log. No other module reads the variable; a provider call gets the credential only as the
 * argument `withOwnKey` passes to it. Delete, 30 minutes without a request, and leaving the
 * page all clear it.
 */

export const OWN_KEY_PROVIDERS = [
  "openai",
  "anthropic",
  "gemini",
  "openrouter",
  "mistral",
  "groq",
  "deepseek",
  "local",
] as const;
export type OwnKeyProvider = (typeof OWN_KEY_PROVIDERS)[number];

/** What the page may show about a held key: the provider and the model, never the key. */
export interface HeldModel {
  provider: OwnKeyProvider;
  model: string;
}

/** What a provider call is made with. */
export interface ProviderCredential extends HeldModel {
  key: string;
  /** The OpenAI-compatible base address of a local server; only for `local`. */
  baseUrl?: string;
}

export interface OwnKeyInput {
  provider: string;
  model: string;
  key: string;
  baseUrl?: string;
}

export const OWN_KEY_IDLE_MS = 30 * 60 * 1000;
const MAX_KEY_LENGTH = 1024;
const MAX_MODEL_LENGTH = 256;
/** Printable ASCII without a space: what a header value and a model id can carry. */
const TOKEN = /^[\x21-\x7e]+$/;

let held: ProviderCredential | null = null;
let shown: HeldModel | null = null;
let idle: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

function armIdleTimer() {
  clearTimeout(idle);
  idle = setTimeout(clearOwnKey, OWN_KEY_IDLE_MS);
}

export function isOwnKeyProvider(value: string): value is OwnKeyProvider {
  return (OWN_KEY_PROVIDERS as readonly string[]).includes(value);
}

/**
 * A local server's base address, when it is `http://localhost:<port>` or
 * `http://127.0.0.1:<port>` with an optional path, without the trailing slash; else null.
 */
export function localBaseUrl(text: string): string | null {
  let url: URL;
  try {
    url = new URL(text.trim());
  } catch {
    return null;
  }
  if (
    url.protocol !== "http:" ||
    (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") ||
    !url.port ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    return null;
  return `${url.origin}${url.pathname.replace(/\/+$/, "")}`;
}

/** Holds the member's key for this tab. Returns false, holding nothing new, when invalid. */
export function setOwnKey({ provider, model, key, baseUrl }: OwnKeyInput): boolean {
  const name = model.trim();
  const secret = key.trim();
  if (!isOwnKeyProvider(provider)) return false;
  if (!name || name.length > MAX_MODEL_LENGTH || !TOKEN.test(name)) return false;
  // A local server may take no key; every hosted provider needs one.
  if (secret.length > MAX_KEY_LENGTH || (secret && !TOKEN.test(secret))) return false;
  if (!secret && provider !== "local") return false;
  const base = provider === "local" ? localBaseUrl(baseUrl ?? "") : null;
  if (provider === "local" && !base) return false;
  held = { provider, model: name, key: secret, ...(base ? { baseUrl: base } : {}) };
  shown = { provider, model: name };
  armIdleTimer();
  notify();
  return true;
}

/** Deletes the held key at once. */
export function clearOwnKey(): void {
  clearTimeout(idle);
  idle = undefined;
  if (held === null && shown === null) return;
  held = null;
  shown = null;
  notify();
}

/** The provider and model of the held key, or null. */
export function heldModel(): HeldModel | null {
  return shown;
}

/**
 * Runs one provider call with the held key, and counts it as a request for the idle timer.
 * Rejects without calling when no key is held.
 */
export function withOwnKey<T>(call: (credential: ProviderCredential) => Promise<T>): Promise<T> {
  const credential = held;
  if (!credential) return Promise.reject(new Error("No model key is held."));
  armIdleTimer();
  return call(credential);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The provider and model of the held key for a component, or null; updates on change. */
export function useOwnKey(): HeldModel | null {
  return useSyncExternalStore(subscribe, heldModel, () => null);
}

// A page kept in the back-forward cache would otherwise come back with the key.
if (typeof window !== "undefined") window.addEventListener("pagehide", clearOwnKey);
