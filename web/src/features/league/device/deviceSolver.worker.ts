/**
 * The device solve, off the page's thread. One message in (the two published documents
 * and the selection), and out the answer or why there is none (`replies.ts`): for chip
 * gains, the plain plan first and the gains after it. The solver is loaded once per worker
 * and the wasm binary comes from the app's own assets, so nothing is fetched from anywhere
 * but the site.
 */

import { highs } from "./lp/highs";
import { replyTo, type DevicePlanReply } from "./replies";
import type { DevicePlanRequest } from "./requests";
import { withinCeiling } from "./solve/ceiling";

export type { DevicePlanRequest } from "./requests";
export type { DevicePlanReply } from "./replies";

self.onmessage = async (event: MessageEvent<DevicePlanRequest>) => {
  const { id } = event.data;
  let loaded: Awaited<ReturnType<typeof highs>>;
  try {
    loaded = await highs();
  } catch {
    self.postMessage({ id, kind: "failed" } satisfies DevicePlanReply);
    return;
  }
  // The page shows the solver as loading until here, and as computing from here.
  self.postMessage({ id, kind: "ready" } satisfies DevicePlanReply);
  // Every solve of the request shares one ceiling; a solve it stops is refused. A chip
  // gain it stops is unknown, and the plain plan solved before it is still the answer.
  replyTo(withinCeiling(loaded), event.data, (reply) => self.postMessage(reply));
};
