/**
 * The compute flow as a state machine: request, wait with the published answer
 * showing, land on the computed one.
 *
 * While the backend works, the member is not staring at a spinner: the previously
 * published saf-puan/1 baseline is fetched and shown as the fallback — the plan's
 * "beklerken önceden yayınlanmış cevap gösterilir". Every terminal state is explicit,
 * and "the backend cannot help" degrades to whatever the static tree can show,
 * never to an error page.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { AdviceClient, AdviceRequest, AdviceSource } from "./adviceClient";
import { StaticOnlyAdviceClient } from "./adviceClient";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 150; // five minutes of patience, then an honest failure

export type ComputePhase =
  | { phase: "idle" }
  | { phase: "requesting" }
  | {
      phase: "waiting";
      jobId: string;
      status: "queued" | "running";
      fallback: LeagueViewEnvelope<EntryAdvice> | null;
    }
  | { phase: "done"; envelope: LeagueViewEnvelope<EntryAdvice>; source: AdviceSource }
  | { phase: "unavailable" }
  | { phase: "failed" };

export function useAdviceJob(client: AdviceClient): {
  state: ComputePhase;
  compute: (request: AdviceRequest) => void;
  reset: () => void;
} {
  const [state, setState] = useState<ComputePhase>({ phase: "idle" });
  const generation = useRef(0);

  useEffect(() => {
    return () => {
      generation.current += 1; // unmount cancels any in-flight poll loop
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    setState({ phase: "idle" });
  }, []);

  const compute = useCallback(
    (request: AdviceRequest) => {
      const run = ++generation.current;
      const alive = () => generation.current === run;
      setState({ phase: "requesting" });

      void (async () => {
        let outcome;
        try {
          outcome = await client.requestAdvice(request);
        } catch {
          if (alive()) setState({ phase: "failed" });
          return;
        }
        if (!alive()) return;
        if (outcome.kind === "advice") {
          setState({ phase: "done", envelope: outcome.envelope, source: outcome.source });
          return;
        }
        if (outcome.kind === "unavailable") {
          setState({ phase: "unavailable" });
          return;
        }

        // A job: fetch the published baseline once, show it while we wait.
        let fallback: LeagueViewEnvelope<EntryAdvice> | null = null;
        try {
          const published = await new StaticOnlyAdviceClient().readAdvice({
            ...request,
            strategy: "saf-puan",
            window: 1,
          });
          if (published.kind === "advice") fallback = published.envelope;
        } catch {
          fallback = null; // the wait is just quieter
        }
        if (!alive()) return;
        setState({ phase: "waiting", jobId: outcome.jobId, status: "queued", fallback });

        for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
          if (!alive()) return;
          let job;
          try {
            job = await client.readJob(outcome.jobId);
          } catch {
            continue; // one flaky poll is not a failed computation
          }
          if (!alive()) return;
          if (job.status === "completed") {
            const read = await client.readAdvice(request);
            if (!alive()) return;
            if (read.kind === "advice") {
              setState({ phase: "done", envelope: read.envelope, source: read.source });
            } else {
              setState({ phase: "failed" }); // completed but unreadable: say so
            }
            return;
          }
          if (job.status === "failed") {
            setState({ phase: "failed" });
            return;
          }
          setState({
            phase: "waiting",
            jobId: outcome.jobId,
            status: job.status,
            fallback,
          });
        }
        if (alive()) setState({ phase: "failed" });
      })();
    },
    [client],
  );

  return { state, compute, reset };
}
