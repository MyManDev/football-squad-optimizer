import type { DevicePlanRequest } from "../requests";
import type { DevicePlanReply } from "../replies";
import { kernel, probe } from "./kernel";

const worker = new Worker(new URL("./diagnostic.worker.ts", import.meta.url), { type: "module" });
const loaded = new Promise<void>((resolve, reject) => {
  worker.onmessage = ({ data }: MessageEvent<{ kind: string }>) => {
    if (data.kind === "loaded") resolve();
  };
  worker.onerror = () => reject(new Error("Diagnostic worker did not load"));
});

async function workerProbe(count: number, warmup: number) {
  await loaded;
  return new Promise<{ milliseconds: number; checksum: number }>((resolve, reject) => {
    worker.onmessage = ({ data }) => resolve(data);
    worker.onerror = () => reject(new Error("Worker calibration failed"));
    worker.postMessage({ kind: "probe", count, warmup });
  });
}

const benchmark = {
  ready: () => loaded,
  async calibrate(count: number, repeats: number) {
    await loaded;
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
  async solve(request: DevicePlanRequest) {
    await loaded;
    const started = performance.now();
    return new Promise<{ reply: DevicePlanReply | { kind: "timeout" }; elapsed_seconds: number }>(
      (resolve) => {
        const timeout = window.setTimeout(() => {
          worker.terminate();
          resolve({
            reply: { kind: "timeout" },
            elapsed_seconds: (performance.now() - started) / 1000,
          });
        }, 315_000);
        worker.onmessage = ({ data }: MessageEvent<DevicePlanReply>) => {
          if (data.kind !== "answer" && data.kind !== "refused" && data.kind !== "failed") return;
          window.clearTimeout(timeout);
          resolve({ reply: data, elapsed_seconds: (performance.now() - started) / 1000 });
        };
        worker.onerror = () => {
          window.clearTimeout(timeout);
          resolve({
            reply: { id: request.id, kind: "failed" },
            elapsed_seconds: (performance.now() - started) / 1000,
          });
        };
        worker.postMessage({ kind: "solve", request });
      },
    );
  },
};

declare global {
  interface Window {
    deviceBenchmark: typeof benchmark;
  }
}
window.deviceBenchmark = benchmark;
