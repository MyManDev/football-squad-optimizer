/// <reference types="node" />
// @vitest-environment node
/**
 * How the wait is going, as the page reads it from `advice_job_view_v1`: the contract's own
 * examples read as they stand, a value outside the contract's rules is not said, and neither
 * that nor a service older than the fields ever decides the job.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { HttpAdviceClient, type AdviceJobStatus } from "./adviceClient";

/** The committed examples the service's own test holds its job view to. */
const EXAMPLES = JSON.parse(
  readFileSync(
    new URL("../../../../../docs/contracts/advice_job_view_v1.examples.json", import.meta.url),
    "utf-8",
  ),
) as Record<string, { job_id: string; status: AdviceJobStatus["status"] }>;

const JOB = "advice-0123456789abcdef-1";

function readView(view: object, jobId = JOB): Promise<AdviceJobStatus> {
  const client = new HttpAdviceClient(
    "https://api.example",
    async () => new Response(JSON.stringify({ job_id: jobId, ...view }), { status: 200 }),
  );
  return client.readJob(jobId);
}

describe("the contract's examples", () => {
  it.each([
    ["queued", { queuePosition: 2, workers: { busy: 1, total: 1 } }],
    ["running", { progress: { done: 1, total: 3 }, workers: { busy: 1, total: 1 } }],
    ["completed", { workers: { busy: 0, total: 1 } }],
    ["failed", { errorCode: "ADVICE_FAILED" }],
  ])("reads the %s job as its example says", async (status, said) => {
    const example = EXAMPLES[status]!;
    expect(example.status).toBe(status);
    expect(await readView(example, example.job_id)).toStrictEqual({
      jobId: example.job_id,
      status,
      attempt: 1,
      ...said,
    });
  });

  it("has an example for every status the page reads, and no other", () => {
    expect(Object.keys(EXAMPLES).sort()).toEqual(["completed", "failed", "queued", "running"]);
  });
});

describe("what the service does not say", () => {
  it.each(["queued", "running", "completed", "failed"])(
    "an older service's %s job answers its status alone",
    async (status) => {
      expect(await readView({ status })).toStrictEqual({ jobId: JOB, status });
    },
  );

  it.each(["queued", "running", "completed", "failed"])(
    "a %s job with all three null answers its status alone",
    async (status) => {
      const view = { status, queue_position: null, progress: null, workers: null };
      expect(await readView(view)).toStrictEqual({ jobId: JOB, status });
    },
  );

  it("reads a job that is next in line, a first count and no busy workers", async () => {
    expect(
      await readView({ status: "queued", queue_position: 0, workers: { busy: 0, total: 3 } }),
    ).toStrictEqual({
      jobId: JOB,
      status: "queued",
      queuePosition: 0,
      workers: { busy: 0, total: 3 },
    });
    expect(await readView({ status: "running", progress: { done: 0, total: 1 } })).toStrictEqual({
      jobId: JOB,
      status: "running",
      progress: { done: 0, total: 1 },
    });
    expect(await readView({ status: "running", progress: { done: 3, total: 3 } })).toStrictEqual({
      jobId: JOB,
      status: "running",
      progress: { done: 3, total: 3 },
    });
  });
});

describe("a value outside the contract's rules is not said, and the job answers", () => {
  it.each([
    ["a position in words", { status: "queued", queue_position: "2" }],
    ["a negative position", { status: "queued", queue_position: -1 }],
    ["a fractional position", { status: "queued", queue_position: 1.5 }],
    ["a position on a running job", { status: "running", queue_position: 2 }],
    ["a position on a finished job", { status: "completed", queue_position: 0 }],
    ["a count on a queued job", { status: "queued", progress: { done: 1, total: 3 } }],
    ["a count on a finished job", { status: "completed", progress: { done: 3, total: 3 } }],
    ["a count past its total", { status: "running", progress: { done: 4, total: 3 } }],
    ["a count of nothing", { status: "running", progress: { done: 0, total: 0 } }],
    ["a count as one number", { status: "running", progress: 0.5 }],
    ["a count in words", { status: "running", progress: { done: "1", total: "3" } }],
    ["a fractional count", { status: "running", progress: { done: 0.5, total: 3 } }],
    ["a count with no total", { status: "running", progress: { done: 1 } }],
    ["more workers busy than alive", { status: "running", workers: { busy: 2, total: 1 } }],
    ["workers with no counts", { status: "running", workers: {} }],
    ["workers as one number", { status: "running", workers: 3 }],
    ["a negative worker count", { status: "queued", workers: { busy: -1, total: 1 } }],
    ["a fractional worker count", { status: "queued", workers: { busy: 0.5, total: 1 } }],
    ["an attempt in words", { status: "running", attempt: "1" }],
  ])("%s", async (_name, view) => {
    expect(await readView(view)).toStrictEqual({ jobId: JOB, status: view.status });
  });
});

describe("the answer that accepts a press", () => {
  const accept = (body: object) =>
    new HttpAdviceClient(
      "https://api.example",
      async () => new Response(JSON.stringify({ job_id: JOB, ...body }), { status: 202 }),
    ).requestAdvice({ leagueId: 352490, entryId: 35249001, strategy: "saf-puan", window: 1 });

  it.each(["queued", "running"])("carries the job's word when it says %s", async (status) => {
    expect(await accept({ status })).toStrictEqual({ kind: "job", jobId: JOB, status });
  });

  it.each([{}, { status: "completed" }, { status: 1 }, { status: null }])(
    "says no word for %j",
    async (body) => {
      expect(await accept(body)).toStrictEqual({ kind: "job", jobId: JOB });
    },
  );
});
