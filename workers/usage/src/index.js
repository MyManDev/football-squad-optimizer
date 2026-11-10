// The usage Worker's entry point (worker.js holds the handler, rules.js the rules). It exports
// nothing but the default handler: the runtime reads every export of this module.

import { createWorker } from "./worker.js";

const worker = createWorker();

export default {
  fetch: (request, env, ctx) => worker.fetch(request, env, ctx),
};
