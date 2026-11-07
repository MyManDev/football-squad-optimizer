// The deadline reminder Worker's entry point (worker.js holds the handlers, rules.js the
// rules, webpush.js the protocol). It exports nothing but the default handlers: the runtime
// reads every export of this module.

import { createWorker } from "./worker.js";

const worker = createWorker();

export default {
  fetch: (request, env, ctx) => worker.fetch(request, env, ctx),
  scheduled: (event, env, ctx) => worker.scheduled(event, env, ctx),
};
