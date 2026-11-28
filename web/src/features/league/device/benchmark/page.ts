import type { DevicePlanRequest } from "../requests";
import { replyTo, type DevicePlanReply } from "../replies";
import { highs } from "../lp/highs";
import { withinCeiling } from "../solve/ceiling";
import { kernel, probe } from "./kernel";

let worker: Worker;
let loaded: Promise<void> | undefined;
function workerReady() {
  loaded ??= new Promise<void>((resolve, reject) => {
    worker = new Worker(new URL("./diagnostic.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }: MessageEvent<{ kind: string }>) => {
      if (data.kind === "loaded") resolve();
    };
    worker.onerror = () => reject(new Error("Diagnostic worker did not load"));
  });
  return loaded;
}

async function workerProbe(count: number, warmup: number) {
  await workerReady();
  return new Promise<{ milliseconds: number; checksum: number }>((resolve, reject) => {
    worker.onmessage = ({ data }) => resolve(data);
    worker.onerror = () => reject(new Error("Worker calibration failed"));
    worker.postMessage({ kind: "probe", count, warmup });
  });
}

const benchmark = {
  ready: workerReady,
  readyMain: () => highs().then(() => undefined),
  async calibrate(count: number, repeats: number) {
    await Promise.all([workerReady(), highs()]);
    // Long warmup in both contexts before the repeated long CPU-only kernel.
    kernel(200_000_000);
    await workerProbe(200_000_000, 2_000_000);
    const main = [],
      dedicatedWorker = [];
    for (let repeat = 0; repeat < repeats; repeat += 1) {
      main.push(probe(count));
      dedicatedWorker.push(await workerProbe(count, 0));
    }
    return { main, dedicatedWorker };
  },
  async solve(request: DevicePlanRequest, audit = false) {
    await workerReady();
    const started = performance.now();
    let model: string | null | undefined;
    return new Promise<{
      reply: DevicePlanReply | { kind: "timeout" };
      elapsed_seconds: number;
      model_sha256?: string | null;
    }>((resolve) => {
      const timeout = window.setTimeout(() => {
        worker.terminate();
        resolve({
          reply: { kind: "timeout" },
          elapsed_seconds: (performance.now() - started) / 1000,
        });
      }, 315_000);
      worker.onmessage = ({
        data,
      }: MessageEvent<DevicePlanReply | { kind: "model"; sha256: string | null }>) => {
        if (data.kind === "model") {
          model = data.sha256;
          return;
        }
        if (data.kind !== "answer" && data.kind !== "refused" && data.kind !== "failed") return;
        window.clearTimeout(timeout);
        resolve({
          reply: data,
          elapsed_seconds: (performance.now() - started) / 1000,
          ...(audit ? { model_sha256: model } : {}),
        });
      };
      worker.onerror = () => {
        window.clearTimeout(timeout);
        resolve({
          reply: { id: request.id, kind: "failed" },
          elapsed_seconds: (performance.now() - started) / 1000,
        });
      };
      worker.postMessage({ kind: "solve", request, audit });
    });
  },
  async solveMain(request: DevicePlanRequest) {
    const solver = await highs();
    const started = performance.now();
    let reply: DevicePlanReply = { id: request.id, kind: "failed" };
    replyTo(withinCeiling(solver, 300), request, (value) => {
      reply = value;
    });
    return { reply, elapsed_seconds: (performance.now() - started) / 1000 };
  },
};

declare global {
  interface Window {
    deviceBenchmark: typeof benchmark;
  }
}
window.deviceBenchmark = benchmark;
