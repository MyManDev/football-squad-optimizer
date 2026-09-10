import { useEffect, useMemo } from "react";

import { createAdviceClient } from "../advice/adviceClient";
import { resolvePublishedAdvice } from "../advice/adviceSelection";
import { AdviceContextError, checkedAdvice } from "../advice/adviceResponse";
import { sameAdviceRequest, useAdviceJob } from "../advice/useAdviceJob";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import type { LeagueMemberViewProps, ShownAdvice } from "./memberPageTypes";

/** Select/reset advice for the current URL while rejecting stale publication context. */
export function useMemberAdviceView(
  {
    squad,
    advice,
    adviceIssue,
    adviceLoading = false,
    members = [],
    index = null,
    client,
  }: LeagueMemberViewProps,
  searchParams: URLSearchParams,
) {
  const view = squad.payload;
  const adviceClient = useMemo(() => client ?? createAdviceClient(), [client]);
  const leagueId = view.league_id;
  const entryId = view.entry.entry_id;
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(params, leagueId, entryId, members, index, {
      season: view.season,
      gameweek: view.gameweek,
    });
  const selection = resolve(searchParams);
  const { request } = selection;
  const indexReadable = adviceIssue !== "index-missing" && adviceIssue !== "index-error";
  const selectionAvailable = !adviceLoading && indexReadable && selection.status === "ready";
  const baselineAvailable =
    resolve(new URLSearchParams("mode=saf-puan&window=1")).status === "ready";
  const job = useAdviceJob(adviceClient, baselineAvailable);
  const requestKey = [
    request.leagueId,
    request.entryId,
    request.strategy,
    request.window,
    request.rivalEntryId ?? "",
    selection.status,
    selection.path,
  ].join(":");

  // A new selection starts clean: an earlier request's answer, wait or failure must not
  // read as this member's, strategy's, window's or rival's.
  const { reset } = job;
  useEffect(() => {
    reset();
  }, [requestKey, reset]);

  const current =
    selectionAvailable &&
    job.state.phase !== "idle" &&
    sameAdviceRequest(job.state.request, request)
      ? job.state
      : null;
  const computed = current?.phase === "done" ? current : null;
  const waiting = current?.phase === "waiting" ? current : null;
  let published: LeagueViewEnvelope<EntryAdvice> | null = null;
  let rejectedContext = false;
  let rejectedUnreadable = false;
  if (advice && selectionAvailable) {
    try {
      const checked = checkedAdvice(advice, request);
      const snapshot = checked.payload.source_snapshot_id;
      rejectedContext =
        snapshot != null && view.source_snapshot_id != null && snapshot !== view.source_snapshot_id;
      published = rejectedContext ? null : checked;
    } catch (error) {
      rejectedContext = error instanceof AdviceContextError;
      rejectedUnreadable = !rejectedContext;
    }
  }
  let shown: ShownAdvice | null = null;
  if (computed) {
    shown = {
      envelope: computed.envelope,
      origin: computed.source === "api-cache" ? "computed" : "published",
      source: computed.source,
    };
  } else if (published) {
    shown = { envelope: published, origin: waiting ? "published-while-computing" : "published" };
  } else if (waiting?.fallback) {
    shown = { envelope: waiting.fallback, origin: "baseline-while-computing" };
  }

  return {
    entryId,
    resolve,
    selection,
    indexReadable,
    selectionAvailable,
    job,
    request,
    shown,
    rejectedContext,
    rejectedUnreadable,
  };
}
