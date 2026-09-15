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
 */

import { cancellableDelay, withRequestDeadline } from "../../../data/request";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AdviceClient, AdviceRequest, AdviceSource } from "./adviceClient";
import { AdviceApiError, StaticOnlyAdviceClient } from "./adviceClient";
import { AdviceResponseError, checkedAdvice } from "./adviceResponse";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 150; // pause the browser wait; the worker keeps the same job

export type ComputePhase =
  | { phase: "idle" }
  | { phase: "requesting"; request: AdviceRequest }
  | {
      phase: "waiting" | "paused";
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
  | { phase: "unavailable"; request: AdviceRequest }
  | { phase: "failed"; request: AdviceRequest; errorCode?: string };

export interface AdviceJob {
  state: ComputePhase;
  compute: (request: AdviceRequest) => void;
  reset: () => void;
}

/** Whether two requests ask the same question: same member, strategy, window and rival. */
export function sameAdviceRequest(left: AdviceRequest, right: AdviceRequest): boolean {
  return (
    left.leagueId === right.leagueId &&
    left.entryId === right.entryId &&
    left.strategy === right.strategy &&
    left.window === right.window &&
    left.season === right.season &&
    left.gameweek === right.gameweek &&
    (left.top100WeightPercent ?? null) === (right.top100WeightPercent ?? null) &&
    (left.rivalEntryId ?? null) === (right.rivalEntryId ?? null)
  );
}

export function useAdviceJob(client: AdviceClient, allowPublishedBaseline = true): AdviceJob {
  const [state, setState] = useState<ComputePhase>({ phase: "idle" });
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const resumable = useRef<Extract<ComputePhase, { phase: "waiting" | "paused" }> | null>(null);

  useEffect(() => {
    return () => {
      generation.current += 1;
      active.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    active.current?.abort();
    resumable.current = null;
    setState({ phase: "idle" });
  }, []);

  const compute = useCallback(
    (request: AdviceRequest) => {
      const run = ++generation.current;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      let taskSignal = controller.signal;
      const alive = () => generation.current === run && !taskSignal.aborted;
      setState({ phase: "requesting", request });
      const previous = resumable.current;
      const resume = previous && sameAdviceRequest(previous.request, request) ? previous : null;
      resumable.current = resume;
      const pause = () => {
        if (generation.current !== run) return;
        if (resumable.current) setState({ ...resumable.current, phase: "paused" });
        else setState({ phase: "failed", request });
      };

      void withRequestDeadline(
        async (signal) => {
          taskSignal = signal;
          const options = { signal };
          let outcome;
          try {
            outcome = resume
              ? { kind: "job" as const, jobId: resume.jobId }
              : await client.requestAdvice(request, options);
            if (outcome.kind === "advice") checkedAdvice(outcome.envelope, request);
          } catch {
            if (alive()) setState({ phase: "failed", request });
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
            setState({ phase: "unavailable", request });
            return;
          }

          // Keep the accepted identity even if fetching the optional baseline hangs.
          // Resuming an existing job reuses its baseline and goes straight to polling.
          let fallback: LeagueViewEnvelope<EntryAdvice> | null = resume?.fallback ?? null;
          resumable.current = {
            phase: "waiting",
            request,
            jobId: outcome.jobId,
            status: resume?.status ?? "queued",
            fallback,
          };
          try {
            const published =
              !resume && allowPublishedBaseline
                ? await new StaticOnlyAdviceClient().readAdvice(
                    {
                      ...request,
                      strategy: "saf-puan",
                      window: 1,
                      rivalEntryId: null,
                      top100WeightPercent: null,
                    },
                    options,
                  )
                : null;
            if (published?.kind === "advice") fallback = published.envelope;
          } catch {
            fallback = null; // the wait is just quieter
          }
          if (!alive()) return;
          setState({ phase: "waiting", request, jobId: outcome.jobId, status: "queued", fallback });
          resumable.current = {
            phase: "waiting",
            request,
            jobId: outcome.jobId,
            status: "queued",
            fallback,
          };

          for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
            await cancellableDelay(POLL_INTERVAL_MS, signal);
            signal.throwIfAborted();
            if (!alive()) return;
            let job;
            try {
              job = await client.readJob(outcome.jobId, options);
            } catch (error) {
              if (
                error instanceof AdviceResponseError ||
                (error instanceof AdviceApiError && error.status >= 400 && error.status < 500)
              ) {
                if (alive()) resumable.current = null;
                if (alive()) setState({ phase: "failed", request });
                return;
              }
              continue; // one flaky poll is not a failed computation
            }
            if (!alive()) return;
            if (job.status === "completed") {
              resumable.current = null;
              let read;
              try {
                read = await client.readAdvice(request, options);
                if (read.kind === "advice") checkedAdvice(read.envelope, request);
              } catch {
                // Completed but the answer cannot be read: an honest failure, not a wait
                // that never ends. A stale read from a superseded request changes nothing.
                if (alive()) setState({ phase: "failed", request });
                return;
              }
              if (!alive()) return;
              if (read.kind === "advice") {
                setState({ phase: "done", request, envelope: read.envelope, source: read.source });
              } else {
                setState({ phase: "failed", request }); // completed but unreadable: say so
              }
              return;
            }
            if (job.status === "failed") {
              resumable.current = null;
              setState({ phase: "failed", request, errorCode: job.errorCode });
              return;
            }
            setState({
              phase: "waiting",
              request,
              jobId: outcome.jobId,
              status: job.status,
              fallback,
            });
          }
          if (alive()) pause();
        },
        { signal: controller.signal, timeoutMs: MAX_POLLS * POLL_INTERVAL_MS },
      )
        .catch(() => {
          pause();
        })
        .finally(() => {
          if (active.current === controller) active.current = null;
        });
    },
    [client, allowPublishedBaseline],
  );

  return { state, compute, reset };
}
