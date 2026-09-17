/**
 * The advice client boundary: one interface, two transports, and a fallback rule.
 *
 * The pages will ask this interface for advice and never know which side answered.
 * With no configured backend (`VITE_ADVICE_API_ORIGIN` empty — the default), the
 * static client serves exactly what the published league tree already serves today.
 * With one, the HTTP client reads the backend's cache and can request a computation;
 * and when that backend is down, slow, or broken, the fallback client quietly answers
 * from the static tree instead — the site degrades to what it is today, never to an
 * error. That behaviour is the product requirement stated in the plan, so it lives
 * here in the boundary, not in page-by-page error handling.
 */

import {
  cancellableDelay,
  isAbortError,
  withRequestDeadline,
  type RequestOptions,
} from "../../../data/request";
import type { WindowSize } from "../../moves/modePrices";
import { LeagueDataError, LeagueDataMissing, loadEntryAdvice } from "../data";
import type { AdviceStrategy, EntryAdvice, LeagueViewEnvelope } from "../types";
import { checkedCapabilities, type AdviceCapabilities } from "./adviceCapabilities";
import { AdviceResponseError, checkedAdvice } from "./adviceResponse";

export interface AdviceRequest {
  leagueId: number;
  entryId: number;
  strategy: AdviceStrategy;
  window: WindowSize;
  rivalEntryId?: number | null;
  /**
   * The member's two switches. Absent is off, and a request with both off goes out exactly
   * as it did before the switches existed. A request that states them (the page does once
   * a compute service is configured) also asks for the answer to be held to them.
   */
  top100Weight?: number;
  managersWord?: boolean;
  /** Display context only; the server resolves its own immutable computation inputs. */
  season?: string;
  gameweek?: number;
}

/** Where an answer came from; the page shows capture identity, not a "cached" badge. */
export type AdviceSource = "static" | "api-cache" | "static-fallback";

export type AdviceReadResult =
  | { kind: "advice"; envelope: LeagueViewEnvelope<EntryAdvice>; source: AdviceSource }
  | { kind: "not-computed" };

export type AdviceRequestResult =
  | { kind: "advice"; envelope: LeagueViewEnvelope<EntryAdvice>; source: AdviceSource }
  | { kind: "job"; jobId: string }
  /** `reason` is a service code when a configured service refused or could not be reached. */
  | { kind: "unavailable"; reason?: string | null };

/** One click's identity: sent as `Idempotency-Key`, the same for every retry of that click. */
export interface AdviceRequestOptions extends RequestOptions {
  idempotencyKey?: string;
}

export interface AdviceClient {
  /** Read an already-computed answer; never triggers computation. */
  readAdvice(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult>;
  /** Ask for the answer, computing it if needed (202 + job when it will take time). */
  requestAdvice(
    request: AdviceRequest,
    options?: AdviceRequestOptions,
  ): Promise<AdviceRequestResult>;
  /** Poll one job. */
  readJob(jobId: string, options?: RequestOptions): Promise<AdviceJobStatus>;
  /**
   * What the service computes right now, or null when there is none to ask or it cannot
   * say. Optional: a client without it is a static site, and the page asks nothing.
   */
  readCapabilities?(leagueId: number, options?: RequestOptions): Promise<AdviceCapabilities | null>;
}

export interface AdviceJobStatus {
  jobId: string;
  status: "queued" | "running" | "completed" | "failed";
  /** The service's coded reason for a failed job; never its text. */
  errorCode?: string | null;
}

/** Whether a request asks for a Top 100 setting or the manager's word. */
export function isSwitchedRequest(request: AdviceRequest): boolean {
  return (request.top100Weight ?? 0) !== 0 || request.managersWord === true;
}

type AdviceLoader = (
  entryId: number,
  mode: AdviceStrategy,
  window: WindowSize,
  rivalEntryId?: number | null,
  options?: RequestOptions,
) => Promise<LeagueViewEnvelope<EntryAdvice>>;

/** Serves the published static tree — today's site, byte for byte. */
export class StaticOnlyAdviceClient implements AdviceClient {
  private readonly loader: AdviceLoader;

  constructor(loader: AdviceLoader = loadEntryAdvice) {
    this.loader = loader;
  }

  async readAdvice(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult> {
    // The plain path below is the plan with both switches off. A switched document is
    // read by the page from the one path the index names, never guessed at from here.
    if (isSwitchedRequest(request)) return { kind: "not-computed" };
    try {
      const envelope = checkedAdvice(
        await withRequestDeadline(
          (signal) =>
            this.loader(
              request.entryId,
              request.strategy,
              request.window,
              request.rivalEntryId ?? null,
              { ...options, signal },
            ),
          options,
        ),
        request,
      );
      return { kind: "advice", envelope, source: "static" };
    } catch (error) {
      if (error instanceof LeagueDataMissing) return { kind: "not-computed" };
      throw error;
    }
  }

  async requestAdvice(
    request: AdviceRequest,
    options?: RequestOptions,
  ): Promise<AdviceRequestResult> {
    // The static tree cannot compute; the published answer is the whole menu.
    const read = await this.readAdvice(request, options);
    return read.kind === "advice" ? read : { kind: "unavailable" };
  }

  async readJob(jobId: string, options?: RequestOptions): Promise<AdviceJobStatus> {
    options?.signal?.throwIfAborted();
    // No backend, no jobs: a job id in hand means the configuration changed under us.
    return { jobId, status: "failed" };
  }
}

interface FetchLike {
  (input: string, init?: RequestInit): Promise<Response>;
}

export class AdviceApiError extends LeagueDataError {
  readonly status: number;
  /** The service's stable error code, when the body carried one. */
  readonly code: string | null;
  /** `Retry-After` in seconds, when the browser was allowed to read it. */
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string | null = null, retryAfterSeconds: number | null = null) {
    super(`Advice API answered ${status}.`);
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const SERVICE_CODE = /^[A-Z][A-Z0-9_]{0,63}$/;

/** The refusal as the service coded it. Its message is for operators and is never read. */
async function apiError(response: Response): Promise<AdviceApiError> {
  let code: string | null = null;
  try {
    const body = (await response.json()) as { error?: { code?: unknown } };
    const stated = body?.error?.code;
    if (typeof stated === "string" && SERVICE_CODE.test(stated)) code = stated;
  } catch {
    code = null;
  }
  const header =
    typeof response.headers?.get === "function" ? response.headers.get("Retry-After") : null;
  const retryAfter = header === null ? Number.NaN : Number(header);
  return new AdviceApiError(
    response.status,
    code,
    Number.isFinite(retryAfter) && retryAfter > 0 ? Math.ceil(retryAfter) : null,
  );
}

/** A queue that was only busy says so with 503 and these codes; the same click may ask again. */
const BUSY_CODES = new Set(["NOT_READY", "QUEUE_UNAVAILABLE"]);
const BUSY_RETRIES = 2;
const BUSY_RETRY_MS = 2000;
const BUSY_RETRY_CEILING_MS = 5000;

/** A key the service's pattern accepts, from the platform's generator where there is one. */
export function newIdempotencyKey(): string {
  const random = globalThis.crypto?.randomUUID?.();
  if (random) return random;
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function isRequestRejection(error: unknown): boolean {
  return error instanceof AdviceApiError && error.status >= 400 && error.status < 500;
}

/** Talks to the advice backend; understands 200 (hit), 202 (job), and 404 (not computed). */
export class HttpAdviceClient implements AdviceClient {
  private readonly origin: string;
  private readonly fetcher: FetchLike;

  constructor(origin: string, fetcher: FetchLike = (input, init) => fetch(input, init)) {
    this.origin = origin.replace(/\/$/, "");
    this.fetcher = fetcher;
  }

  private adviceUrl(request: AdviceRequest): string {
    const rival =
      request.rivalEntryId == null ? "" : `&rival=${encodeURIComponent(request.rivalEntryId)}`;
    // Only a switch that is on is named, so a plain request's address does not move.
    const weight = request.top100Weight ? `&top100_weight=${request.top100Weight}` : "";
    const word = request.managersWord === true ? "&managers_word=true" : "";
    return (
      `${this.origin}/api/v1/leagues/${request.leagueId}/entries/${request.entryId}/advice` +
      `?strategy=${encodeURIComponent(request.strategy)}&window=${request.window}${rival}` +
      weight +
      word
    );
  }

  async readAdvice(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult> {
    return withRequestDeadline(async (signal) => {
      const response = await this.fetcher(this.adviceUrl(request), { cache: "no-cache", signal });
      if (response.status === 404) {
        const body = (await response.json()) as { error?: { code?: string } };
        if (body?.error?.code === "NOT_COMPUTED") return { kind: "not-computed" };
        const stated = body?.error?.code;
        throw new AdviceApiError(
          404,
          typeof stated === "string" && SERVICE_CODE.test(stated) ? stated : null,
        );
      }
      if (!response.ok) throw await apiError(response);
      const envelope = checkedAdvice(await response.json(), request);
      return { kind: "advice", envelope, source: "api-cache" };
    }, options);
  }

  async requestAdvice(
    request: AdviceRequest,
    options?: AdviceRequestOptions,
  ): Promise<AdviceRequestResult> {
    const idempotencyKey = options?.idempotencyKey ?? newIdempotencyKey();
    for (let attempt = 0; ; attempt += 1) {
      try {
        return await this.postAdvice(request, idempotencyKey, options);
      } catch (error) {
        const busy =
          error instanceof AdviceApiError &&
          error.status === 503 &&
          error.code !== null &&
          BUSY_CODES.has(error.code);
        // Without a signal nothing could end the wait, so a caller that passes none
        // hears about the first refusal.
        if (!busy || attempt >= BUSY_RETRIES || !options?.signal) throw error;
        const wait = Math.min(
          error.retryAfterSeconds === null ? BUSY_RETRY_MS : error.retryAfterSeconds * 1000,
          BUSY_RETRY_CEILING_MS,
        );
        await cancellableDelay(wait, options.signal);
        options.signal.throwIfAborted();
      }
    }
  }

  private async postAdvice(
    request: AdviceRequest,
    idempotencyKey: string,
    options?: RequestOptions,
  ): Promise<AdviceRequestResult> {
    return withRequestDeadline(async (signal) => {
      const response = await this.fetcher(this.adviceUrl(request), {
        signal,
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          strategy: request.strategy,
          window: request.window,
          rival_entry_id: request.rivalEntryId ?? null,
          ...(request.top100Weight ? { top100_weight: request.top100Weight } : {}),
          ...(request.managersWord === true ? { managers_word: true } : {}),
        }),
      });
      if (response.status === 202) {
        const body = (await response.json()) as { job_id: string };
        if (typeof body?.job_id !== "string" || !body.job_id.trim()) {
          throw new AdviceResponseError("Accepted advice request has no job identity.");
        }
        return { kind: "job", jobId: body.job_id };
      }
      if (!response.ok) throw await apiError(response);
      const envelope = checkedAdvice(await response.json(), request);
      return { kind: "advice", envelope, source: "api-cache" };
    }, options);
  }

  async readJob(jobId: string, options?: RequestOptions): Promise<AdviceJobStatus> {
    return withRequestDeadline(async (signal) => {
      const response = await this.fetcher(
        `${this.origin}/api/v1/advice-jobs/${encodeURIComponent(jobId)}`,
        { cache: "no-cache", signal },
      );
      if (!response.ok) throw await apiError(response);
      const body = (await response.json()) as {
        job_id: string;
        status: AdviceJobStatus["status"];
        error_code?: unknown;
      };
      if (
        body?.job_id !== jobId ||
        !["queued", "running", "completed", "failed"].includes(body?.status)
      ) {
        throw new AdviceResponseError("Advice job response has an invalid identity or status.");
      }
      const errorCode =
        typeof body.error_code === "string" && SERVICE_CODE.test(body.error_code)
          ? body.error_code
          : null;
      return {
        jobId: body.job_id,
        status: body.status,
        ...(errorCode === null ? {} : { errorCode }),
      };
    }, options);
  }

  async readCapabilities(
    leagueId: number,
    options?: RequestOptions,
  ): Promise<AdviceCapabilities | null> {
    return withRequestDeadline(async (signal) => {
      const response = await this.fetcher(
        `${this.origin}/api/v1/leagues/${leagueId}/capabilities`,
        { cache: "no-cache", signal },
      );
      if (!response.ok) throw await apiError(response);
      return checkedCapabilities(await response.json(), leagueId);
    }, options);
  }
}

/**
 * The degradation rule as a client: try the backend, and when it cannot answer —
 * network failure, 5xx — serve the static tree and say so in `source`. A backend 404
 * is not a failure: it honestly says "not computed", and the static tree still gets
 * to answer, because the published baseline may exist where the cache is empty.
 */
export class FallbackAdviceClient implements AdviceClient {
  private readonly primary: AdviceClient;
  private readonly fallback: StaticOnlyAdviceClient;

  constructor(primary: AdviceClient, fallback: StaticOnlyAdviceClient) {
    this.primary = primary;
    this.fallback = fallback;
  }

  async readAdvice(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult> {
    let primaryResult: AdviceReadResult | null = null;
    try {
      primaryResult = await this.primary.readAdvice(request, options);
    } catch (error) {
      if (isRequestRejection(error) || isAbortError(error) || options?.signal?.aborted) throw error;
      primaryResult = null;
    }
    if (primaryResult && primaryResult.kind === "advice") return primaryResult;
    const fallbackResult = await this.fallback.readAdvice(request, options);
    if (fallbackResult.kind === "advice") {
      return primaryResult === null
        ? { ...fallbackResult, source: "static-fallback" }
        : fallbackResult;
    }
    return primaryResult ?? fallbackResult;
  }

  async requestAdvice(
    request: AdviceRequest,
    options?: AdviceRequestOptions,
  ): Promise<AdviceRequestResult> {
    try {
      return await this.primary.requestAdvice(request, options);
    } catch (error) {
      if (isRequestRejection(error) || isAbortError(error) || options?.signal?.aborted) throw error;
      const read = await this.fallback.readAdvice(request, options);
      if (read.kind === "advice") return { ...read, source: "static-fallback" };
      // Nothing published to fall back on: say why the service could not help.
      const code = error instanceof AdviceApiError ? error.code : null;
      return { kind: "unavailable", reason: code ?? SERVICE_UNREACHABLE };
    }
  }

  async readJob(jobId: string, options?: RequestOptions): Promise<AdviceJobStatus> {
    return this.primary.readJob(jobId, options);
  }

  /** Any failure is "no service to ask": the page stays what the static site is. */
  async readCapabilities(
    leagueId: number,
    options?: RequestOptions,
  ): Promise<AdviceCapabilities | null> {
    if (!this.primary.readCapabilities) return null;
    try {
      return await this.primary.readCapabilities(leagueId, options);
    } catch (error) {
      if (isAbortError(error) || options?.signal?.aborted) throw error;
      return null;
    }
  }
}

/** The page's own code for a service that did not answer at all. */
export const SERVICE_UNREACHABLE = "SERVICE_UNREACHABLE";

/** The composition root: empty origin (the default) is today's static site. */
export function createAdviceClient(origin?: string): AdviceClient {
  const configured = origin ?? (import.meta.env.VITE_ADVICE_API_ORIGIN as string | undefined) ?? "";
  if (!configured) return new StaticOnlyAdviceClient();
  return new FallbackAdviceClient(new HttpAdviceClient(configured), new StaticOnlyAdviceClient());
}
