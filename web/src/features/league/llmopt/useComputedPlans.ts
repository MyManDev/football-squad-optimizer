import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { EntryAdvice } from "../types";
import type { PlanSession, PlanSessionStore } from "./planSession";
import {
  addHistory,
  EMPTY_HISTORY,
  planContent,
  planIdentity,
  retainedPlan,
  selectHistory,
  verifiedHistory,
  type PlanHistory,
} from "./planHistory";

export function useComputedPlans(
  session: PlanSessionStore,
  current: PlanSession,
  plans: EntryAdvice[],
  runId?: string,
) {
  const saved = useSyncExternalStore(session.subscribe, () => session.history);
  const [ready, setReady] = useState(false);
  const latest = useRef(current);
  latest.current = current;
  const run = useRef(runId);
  const activate = useRef(false);
  if (run.current !== runId) {
    run.current = runId;
    activate.current = !!runId;
  }
  useEffect(() => {
    let active = true;
    void verifiedHistory(session.history)
      .then((history) => {
        if (!active) return;
        if (history !== session.history) session.save({ ...latest.current, history });
        setReady(true);
      })
      .catch(() => {
        // A browser that cannot verify a stored digest can still keep the archive for a later visit.
        if (active) setReady(false);
      });
    return () => {
      active = false;
    };
  }, [session]);
  const content = plans.map(planContent).join("\n");
  useEffect(() => {
    if (!ready || !plans.length) return;
    let active = true;
    void Promise.all(
      plans.map(async (plan) => ({ id: await planIdentity(plan), plan: retainedPlan(plan) })),
    )
      .then((items) => {
        if (!active) return;
        let history = addHistory(session.history, items);
        if (activate.current && items[0]) {
          history = selectHistory(history, items[0].id, false);
          activate.current = false;
        }
        if (JSON.stringify(history) !== JSON.stringify(session.history))
          session.save({ ...latest.current, history });
      })
      .catch(() => {
        /* Completed cards remain usable without content digests. */
      });
    return () => {
      active = false;
    };
    // Content, rather than response object identity, makes recomputation and rerenders idempotent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, ready, session]);
  const history = ready ? saved : EMPTY_HISTORY;
  const selected = history.items.find((item) => item.id === history.navigation[history.cursor]);
  const idFor = (plan: EntryAdvice) =>
    history.items.find((item) => planContent(item.plan) === planContent(plan))?.id;
  const choose = (id: string) => selectHistory(history, id);
  const move = (offset: number): PlanHistory => {
    const cursor = history.cursor + offset;
    return cursor >= 0 && cursor < history.navigation.length
      ? { ...history, cursor, explicit: true }
      : history;
  };
  return { history, selected, idFor, choose, move };
}
