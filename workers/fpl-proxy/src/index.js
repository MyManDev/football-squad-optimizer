// The FPL forwarder Worker's entry point (worker.js holds the handler, proxy.js the rules). It
// exports nothing but the default handlers: the runtime reads every export of this module.

import { createWorker } from "./worker.js";

export default createWorker();
