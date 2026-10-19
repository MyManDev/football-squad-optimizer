/**
 * The what-if mode's solver (#1132), off the page's thread: one message in (the capture's
 * table and the fifteens to read), one message out (each fifteen's points, or a failure).
 * The solver is the device solve's own HiGHS, loaded once per worker.
 */

import { highs } from "./lp/highs";
import type { DevicePlanDocument } from "./types";
import { whatIfValues } from "./whatIf";

export interface WhatIfRequest {
  id: number;
  /** The capture's table in solver order (`whatIfDocument`). */
  document: DevicePlanDocument;
  squads: number[][];
}

export type WhatIfReply =
  { id: number; kind: "values"; values: (number | null)[] } | { id: number; kind: "failed" };

self.onmessage = async (event: MessageEvent<WhatIfRequest>) => {
  const { id, document, squads } = event.data;
  let reply: WhatIfReply;
  try {
    reply = { id, kind: "values", values: whatIfValues(await highs(), document, squads) };
  } catch {
    reply = { id, kind: "failed" };
  }
  self.postMessage(reply);
};
