/** Opt-in diagnostic build only. The app never imports this worker. */
import { highs } from "../lp/highs";
import { replyTo } from "../replies";
import type { DevicePlanRequest } from "../requests";
import { withinCeiling } from "../solve/ceiling";
import { kernel, probe } from "./kernel";

const loaded = await highs();
self.postMessage({ kind: "loaded" });
self.onmessage = (
  event: MessageEvent<
    { kind: "probe"; count: number; warmup: number } | { kind: "solve"; request: DevicePlanRequest }
  >,
) => {
  if (event.data.kind === "probe") {
    kernel(event.data.warmup);
    self.postMessage({ kind: "probe", ...probe(event.data.count) });
    return;
  }
  // Only diagnostics get 300 seconds to distinguish a slow proof from a 60s refusal.
  // Production and ordinary regression ceilings remain unchanged.
  self.postMessage({ id: event.data.request.id, kind: "ready" });
  replyTo(withinCeiling(loaded, 300), event.data.request, (reply) => self.postMessage(reply));
};
