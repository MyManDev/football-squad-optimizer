/**
 * The compute flow as a state machine: request, wait with the published answer
 * showing, land on the computed one.
 *
 * While the backend works, the member is not staring at a spinner: the previously
 * published saf-puan/1 baseline is fetched and shown as the fallback — the plan's
 * "beklerken önceden yayınlanmış cevap gösterilir". Every terminal state is explicit,
 * and "the backend cannot help" degrades to whatever the static tree can show,
 * never to an error page.
 *
 * Every phase after idle carries the request it answers, so a page can tell a result
 * that belongs to the selection on screen from one left behind by an earlier selection.
 *
 * Patience follows the window asked for, the wait is polled less often after its first
 * minute, a failure keeps the service's coded reason so the panel can say what happened,
 * and the job id is remembered for the tab so a reload resumes the wait.
 */

import { cancellableDelay, withRequestDeadline } from "../../../data/request";
import { useCallback, useEffect, useRef, useState } from "react";

import type { WindowSize } from "../../moves/modePrices";
import type { AdviceClient, AdviceRequest, AdviceSource } from "./adviceClient";
import { AdviceApiError, StaticOnlyAdviceClient, newIdempotencyKey } from "./adviceClient";
import { forgetJob, recallJob, rememberJob, type StoredAdviceJob } from "./adviceJobStore";
import { AdviceContextError, AdviceResponseError, checkedAdvice } from "./adviceResponse";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";

const POLL_INTERVAL_MS = 2000;
// A long solve is asked about less often once its first minute has passed.
const SLOW_POLL_INTERVAL_MS = 5000;
const SLOW_POLL_AFTER_MS = 60_000;
/**
 * How long a wait lasts before it is called a failure, per window. The solves measured on
 * the machine that serves them took seconds, about a minute and a half, and about three
 * and a half minutes; each budget leaves room above that for a queue ahead of the job.
 */
export const PATIENCE_MS: Record<WindowSize, number> = { 1: 180_000, 3: 360_000, 5: 600_000 };
// Sending the request, and reading the answer at the end, are outside the wait itself.
const REQUEST_ALLOWANCE_MS = 30_000;

/** The page's own reasons for a failure, beside the service's codes. */
export const PATIENCE_EXHAUSTED = "PATIENCE_EXHAUSTED";
export const ANSWER_UNREADABLE = "ANSWER_UNREADABLE";
export const ANSWER_MISMATCH = "ANSWER_MISMATCH";
export const ANSWER_OTHER_CAPTURE = "ANSWER_OTHER_CAPTURE";

export type ComputePhase =
  | { phase: "idle" }
  | { phase: "requesting"; request: AdviceRequest }
  | {
      phase: "waiting";
      request: AdviceRequest;
      jobId: string;
      status: "queued" | "running";
      fallback: LeagueViewEnvelope<EntryAdvice> | null;
    }
  | {
      phase: "done";
      request: AdviceRequest;
      envelope: LeagueViewEnvelope<EntryAdvice>;
      source: AdviceSource;
    }
  | { phase: "unavailable"; request: AdviceRequest; reason?: string | null }
  | {
      phase: "failed";
      request: AdviceRequest;
      /** A service code or one of the page's own; the panel turns it into a sentence. */
      reason?: string | null;
      retryAfterSeconds?: number | null;
    };

export interface AdviceJob {
  state: ComputePhase;
  compute: (request: AdviceRequest) => void;
  /** Pick up a wait this tab began before a reload; false when there is none to pick up. */
  resume?: (request: AdviceRequest) => boolean;
  /** Read once without starting a job; an absent, stale or unreadable answer stays silent. */
  readCached?: (request: AdviceRequest) => void;
  reset: () => void;
}

/** Whether two requests ask the same question: same member, strategy, window, rival and switches. */
export function sameAdviceRequest(left: AdviceRequest, right: AdviceRequest): boolean {
  return (
    left.leagueId === right.leagueId &&
    left.entryId === right.entryId &&
    left.strategy === right.strategy &&
    left.window === right.window &&
    left.season === right.season &&
    left.gameweek === right.gameweek &&
    (left.rivalEntryId ?? null) === (right.rivalEntryId ?? null) &&
    (left.top100Weight ?? 0) === (right.top100Weight ?? 0) &&
    (left.managersWord ?? false) === (right.managersWord ?? false) &&
    (left.chip ?? null) === (right.chip ?? null) &&
    (left.model ?? "current") === (right.model ?? "current")
  );
}

function failure(error: unknown): { reason: string | null; retryAfterSeconds: number | null } {
  if (error instanceof AdviceApiError) {
    return { reason: error.code, retryAfterSeconds: error.retryAfterSeconds };
  }
  if (error instanceof AdviceContextError)
    return { reason: ANSWER_MISMATCH, retryAfterSeconds: null };
  if (error instanceof AdviceResponseError) {
    return { reason: ANSWER_UNREADABLE, retryAfterSeconds: null };
  }
  return { reason: null, retryAfterSeconds: null };
}

export function useAdviceJob(
  client: AdviceClient,
  allowPublishedBaseline = true,
  expectedSnapshotId?: string | null,
): AdviceJob {
  const [state, setState] = useState<ComputePhase>({ phase: "idle" });
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      generation.current += 1;
      active.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    active.current?.abort();
    active.current = null;
    setState({ phase: "idle" });
  }, []);

  const readCached = useCallback(
    (request: AdviceRequest) => {
      if (active.current) return;
      const run = ++generation.current;
      const controller = new AbortController();
      active.current = controller;
      void withRequestDeadline(
        async (signal) => {
          const read = await client.readAdvice(request, { signal, publishedFallback: false });
          if (read.kind !== "advice" || signal.aborted || generation.current !== run) return;
          checkedAdvice(read.envelope, request);
          const snapshot = read.envelope.payload.source_snapshot_id;
          if (snapshot != null && expectedSnapshotId != null && snapshot !== expectedSnapshotId)
            return;
          setState((prev) =>
            prev.phase === "idle"
              ? { phase: "done", request, envelope: read.envelope, source: read.source }
              : prev,
          );
        },
        { signal: controller.signal, timeoutMs: REQUEST_ALLOWANCE_MS },
      )
        .catch(() => {
          // A cache miss or failed read leaves the ordinary Compute panel in place.
        })
        .finally(() => {
          if (active.current === controller) active.current = null;
        });
    },
    [client, expectedSnapshotId],
  );

  const start = useCallback(
    (request: AdviceRequest, resumed: StoredAdviceJob | null) => {
      const run = ++generation.current;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      let taskSignal = controller.signal;
      let readAfterMissingJob = false;
      const alive = () => generation.current === run && !taskSignal.aborted;
      const patience = PATIENCE_MS[request.window] ?? PATIENCE_MS[1];
      const fail = (error?: unknown, reason?: string) => {
        if (!alive()) return;
        const stated = failure(error);
        setState({ phase: "failed", request, ...stated, reason: reason ?? stated.reason });
      };
      setState(
        resumed
          ? { phase: "waiting", request, jobId: resumed.jobId, status: "queued", fallback: null }
          : { phase: "requesting", request },
      );

      void withRequestDeadline(
        async (signal) => {
          taskSignal = signal;
          const options = { signal };
          let jobId: string;
          let startedAt: number;
          if (resumed) {
            ({ jobId, startedAt } = resumed);
          } else {
            let outcome;
            try {
              // One key for this click, whatever the transport retries underneath it.
              outcome = await client.requestAdvice(request, {
                ...options,
                idempotencyKey: newIdempotencyKey(),
              });
              if (outcome.kind === "advice") checkedAdvice(outcome.envelope, request);
            } catch (error) {
              fail(error);
              return;
            }
            if (!alive()) return;
            if (outcome.kind === "advice") {
              setState({
                phase: "done",
                request,
                envelope: outcome.envelope,
                source: outcome.source,
              });
              return;
            }
            if (outcome.kind === "unavailable") {
              setState({ phase: "unavailable", request, reason: outcome.reason ?? null });
              return;
            }
            jobId = outcome.jobId;
            startedAt = Date.now();
            rememberJob(request, { jobId, startedAt });
          }

          // A job: fetch the published baseline once, show it while we wait.
          let fallback: LeagueViewEnvelope<EntryAdvice> | null = null;
          try {
            const published = allowPublishedBaseline
              ? await new StaticOnlyAdviceClient().readAdvice(
                  {
                    ...request,
                    strategy: "saf-puan",
                    window: 1,
                    rivalEntryId: null,
                    top100Weight: undefined,
                    managersWord: undefined,
                    chip: undefined,
                  },
                  options,
                )
              : null;
            if (published?.kind === "advice") fallback = published.envelope;
          } catch {
            fallback = null; // the wait is just quieter
          }
          if (!alive()) return;
          setState({ phase: "waiting", request, jobId, status: "queued", fallback });

          while (Date.now() - startedAt < patience) {
            const waited = Date.now() - startedAt;
            await cancellableDelay(
              waited < SLOW_POLL_AFTER_MS ? POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS,
              signal,
            );
            signal.throwIfAborted();
            if (!alive()) return;
            let job;
            try {
              job = await client.readJob(jobId, options);
            } catch (error) {
              if (
                error instanceof AdviceResponseError ||
                (error instanceof AdviceApiError && error.status >= 400 && error.status < 500)
              ) {
                if (!alive()) return;
                forgetJob(request);
                // A remembered job the service no longer knows is not this visit's
                // failure: the page is simply back where a fresh visit starts.
                if (resumed && error instanceof AdviceApiError && error.status === 404) {
                  setState({ phase: "idle" });
                  readAfterMissingJob = true;
                } else {
                  fail(error);
                }
                return;
              }
              continue; // one flaky poll is not a failed computation
            }
            if (!alive()) return;
            if (job.status === "completed") {
              forgetJob(request);
              let read;
              try {
                read = await client.readAdvice(request, options);
                if (read.kind === "advice") checkedAdvice(read.envelope, request);
              } catch (error) {
                // Completed but the answer cannot be read: an honest failure, not a wait
                // that never ends. A stale read from a superseded request changes nothing.
                fail(error, failure(error).reason ?? ANSWER_UNREADABLE);
                return;
              }
              if (!alive()) return;
              if (read.kind === "advice") {
                setState({ phase: "done", request, envelope: read.envelope, source: read.source });
              } else {
                fail(undefined, ANSWER_UNREADABLE); // completed but unreadable: say so
              }
              return;
            }
            if (job.status === "failed") {
              forgetJob(request);
              fail(undefined, job.errorCode ?? undefined);
              return;
            }
            setState({ phase: "waiting", request, jobId, status: job.status, fallback });
          }
          if (alive()) {
            forgetJob(request);
            fail(undefined, PATIENCE_EXHAUSTED);
          }
        },
        {
          signal: controller.signal,
          timeoutMs:
            REQUEST_ALLOWANCE_MS +
            Math.max(patience - (resumed ? Date.now() - resumed.startedAt : 0), 0),
        },
      )
        .catch(() => {
          if (generation.current === run) {
            forgetJob(request);
            setState({ phase: "failed", request, reason: PATIENCE_EXHAUSTED });
          }
        })
        .finally(() => {
          if (active.current === controller) active.current = null;
          if (readAfterMissingJob && generation.current === run) readCached(request);
        });
    },
    [client, allowPublishedBaseline, readCached],
  );

  const compute = useCallback((request: AdviceRequest) => start(request, null), [start]);

  const resume = useCallback(
    (request: AdviceRequest) => {
      const remembered = recallJob(request);
      if (!remembered) return false;
      const age = Date.now() - remembered.startedAt;
      if (age < 0 || age >= (PATIENCE_MS[request.window] ?? PATIENCE_MS[1])) {
        forgetJob(request);
        return false;
      }
      start(request, remembered);
      return true;
    },
    [start],
  );

  return { state, compute, resume, readCached, reset };
}
