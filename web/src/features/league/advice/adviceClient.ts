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

import type { PlayMode, WindowSize } from "../../moves/modePrices";
import { LeagueDataError, LeagueDataMissing, loadEntryAdvice } from "../data";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";

export interface AdviceRequest {
  leagueId: number;
  entryId: number;
  strategy: PlayMode;
  window: WindowSize;
  rivalEntryId?: number | null;
}

/** Where an answer came from; the page shows capture identity, not a "cached" badge. */
export type AdviceSource = "static" | "api-cache" | "static-fallback";

export type AdviceReadResult =
  | { kind: "advice"; envelope: LeagueViewEnvelope<EntryAdvice>; source: AdviceSource }
  | { kind: "not-computed" };

export type AdviceRequestResult =
  | { kind: "advice"; envelope: LeagueViewEnvelope<EntryAdvice>; source: AdviceSource }
  | { kind: "job"; jobId: string }
  | { kind: "unavailable" };

export interface AdviceClient {
  /** Read an already-computed answer; never triggers computation. */
  readAdvice(request: AdviceRequest): Promise<AdviceReadResult>;
  /** Ask for the answer, computing it if needed (202 + job when it will take time). */
  requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult>;
  /** Poll one job. */
  readJob(jobId: string): Promise<AdviceJobStatus>;
}

export interface AdviceJobStatus {
  jobId: string;
  status: "queued" | "running" | "completed" | "failed";
}

type AdviceLoader = (
  entryId: number,
  mode: PlayMode,
  window: WindowSize,
) => Promise<LeagueViewEnvelope<EntryAdvice>>;

/** Serves the published static tree — today's site, byte for byte. */
export class StaticOnlyAdviceClient implements AdviceClient {
  private readonly loader: AdviceLoader;

  constructor(loader: AdviceLoader = loadEntryAdvice) {
    this.loader = loader;
  }

  async readAdvice(request: AdviceRequest): Promise<AdviceReadResult> {
    try {
      const envelope = await this.loader(request.entryId, request.strategy, request.window);
      return { kind: "advice", envelope, source: "static" };
    } catch (error) {
      if (error instanceof LeagueDataMissing) return { kind: "not-computed" };
      throw error;
    }
  }

  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    // The static tree cannot compute; the published answer is the whole menu.
    const read = await this.readAdvice(request);
    return read.kind === "advice" ? read : { kind: "unavailable" };
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    // No backend, no jobs: a job id in hand means the configuration changed under us.
    return { jobId, status: "failed" };
  }
}

interface FetchLike {
  (input: string, init?: RequestInit): Promise<Response>;
}

/** Talks to the advice backend; understands 200 (hit), 202 (job), and 404 (not computed). */
export class HttpAdviceClient implements AdviceClient {
  private readonly origin: string;
  private readonly fetcher: FetchLike;

  constructor(origin: string, fetcher: FetchLike = fetch) {
    this.origin = origin.replace(/\/$/, "");
    this.fetcher = fetcher;
  }

  private adviceUrl(request: AdviceRequest): string {
    const rival =
      request.rivalEntryId == null ? "" : `&rival=${encodeURIComponent(request.rivalEntryId)}`;
    return (
      `${this.origin}/api/v1/leagues/${request.leagueId}/entries/${request.entryId}/advice` +
      `?strategy=${encodeURIComponent(request.strategy)}&window=${request.window}${rival}`
    );
  }

  async readAdvice(request: AdviceRequest): Promise<AdviceReadResult> {
    const response = await this.fetcher(this.adviceUrl(request), { cache: "no-cache" });
    if (response.status === 404) return { kind: "not-computed" };
    if (!response.ok) throw new LeagueDataError(`Advice API answered ${response.status}.`);
    const envelope = (await response.json()) as LeagueViewEnvelope<EntryAdvice>;
    return { kind: "advice", envelope, source: "api-cache" };
  }

  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    const response = await this.fetcher(this.adviceUrl(request), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        strategy: request.strategy,
        window: request.window,
        rival_entry_id: request.rivalEntryId ?? null,
      }),
    });
    if (response.status === 202) {
      const body = (await response.json()) as { job_id: string };
      return { kind: "job", jobId: body.job_id };
    }
    if (!response.ok) throw new LeagueDataError(`Advice API answered ${response.status}.`);
    const envelope = (await response.json()) as LeagueViewEnvelope<EntryAdvice>;
    return { kind: "advice", envelope, source: "api-cache" };
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    const response = await this.fetcher(
      `${this.origin}/api/v1/advice-jobs/${encodeURIComponent(jobId)}`,
      { cache: "no-cache" },
    );
    if (!response.ok) throw new LeagueDataError(`Advice API answered ${response.status}.`);
    const body = (await response.json()) as { job_id: string; status: AdviceJobStatus["status"] };
    return { jobId: body.job_id, status: body.status };
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

  async readAdvice(request: AdviceRequest): Promise<AdviceReadResult> {
    let primaryResult: AdviceReadResult | null = null;
    try {
      primaryResult = await this.primary.readAdvice(request);
    } catch {
      primaryResult = null;
    }
    if (primaryResult && primaryResult.kind === "advice") return primaryResult;
    const fallbackResult = await this.fallback.readAdvice(request);
    if (fallbackResult.kind === "advice") {
      return primaryResult === null
        ? { ...fallbackResult, source: "static-fallback" }
        : fallbackResult;
    }
    return primaryResult ?? fallbackResult;
  }

  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    try {
      return await this.primary.requestAdvice(request);
    } catch {
      const read = await this.fallback.readAdvice(request);
      return read.kind === "advice"
        ? { ...read, source: "static-fallback" }
        : { kind: "unavailable" };
    }
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    return this.primary.readJob(jobId);
  }
}

/** The composition root: empty origin (the default) is today's static site. */
export function createAdviceClient(origin?: string): AdviceClient {
  const configured = origin ?? (import.meta.env.VITE_ADVICE_API_ORIGIN as string | undefined) ?? "";
  if (!configured) return new StaticOnlyAdviceClient();
  return new FallbackAdviceClient(new HttpAdviceClient(configured), new StaticOnlyAdviceClient());
}
