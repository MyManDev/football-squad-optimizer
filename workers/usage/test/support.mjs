// What the tests build their requests from: a fake dataset and a valid event. No network and
// no credentials.

import { createWorker } from "../src/worker.js";

export const SITE = "https://squadopt.mymandev.com";
export const SESSION = "0123456789abcdef";

export function goodEvent(overrides = {}) {
  return {
    page: "member",
    tool: "what-if",
    step: "tool",
    lang: "tr",
    device: "phone",
    session: SESSION,
    v: 1,
    ...overrides,
  };
}

/** A worker over a recording dataset, and a way to send it a request. */
export function harness({ dataset } = {}) {
  const written = [];
  const lines = [];
  const env = { USAGE_EVENTS: dataset ?? { writeDataPoint: (point) => written.push(point) } };
  const worker = createWorker({ log: (event, fields) => lines.push({ event, ...fields }) });
  const send = (path, { method = "POST", origin = SITE, body, headers = {} } = {}) =>
    worker.fetch(
      new Request(`${SITE}${path}`, {
        method,
        headers: { ...(origin === null ? {} : { origin }), ...headers },
        body,
      }),
      env,
    );
  return { env, lines, send, worker, written };
}
