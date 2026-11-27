/** Only this owned launcher and its browser descendants enter the temporary CPU job. */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createInterface } from "node:readline";
import { guardedBrowserSolve } from "./watchdog.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const web = resolve(here, "../../../../..");
const project = resolve(web, "..");
const browserDist = resolve(project, ".codex-tmp/real-horizon-browser");
const nodeBundle = resolve(web, ".codex-tmp/real-horizon-node.mjs");
const emit = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);

if (process.argv[2] === "build") {
  const { build } = await import("vite");
  await build({ configFile: resolve(here, "vite.config.mts") });
  await build({
    configFile: false,
    ssr: { external: ["highs"] },
    build: {
      ssr: resolve(here, "node.ts"),
      outDir: resolve(web, ".codex-tmp"),
      emptyOutDir: false,
      target: "node22",
      rolldownOptions: { output: { entryFileNames: "real-horizon-node.mjs" } },
    },
  });
  emit({ event: "built", browserDist, nodeBundle });
} else {
  const lines = createInterface({ input: process.stdin });
  const iterator = lines[Symbol.asyncIterator]();
  emit({ event: "boot", pid: process.pid });
  const gate = await iterator.next();
  if (gate.done || JSON.parse(gate.value).command !== "go") throw new Error("No launcher gate");
  const runtime = process.argv[2];
  let server, browserServer, browser, page, solve, cdp;
  let currentRate = 1;
  async function openPage() {
    page = await browser.newPage();
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(() => !!window.deviceBenchmark);
    await page.evaluate(
      (main) => (main ? window.deviceBenchmark.readyMain() : window.deviceBenchmark.ready()),
      runtime === "main",
    );
    cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: currentRate });
    solve =
      runtime === "main"
        ? (request) => page.evaluate((value) => window.deviceBenchmark.solveMain(value), request)
        : (request, audit = false) =>
            page.evaluate(({ value, inspect }) => window.deviceBenchmark.solve(value, inspect), {
              value: request,
              inspect: audit,
            });
  }
  async function replaceOwnContext() {
    let closed = false;
    await Promise.race([
      page
        .context()
        .close()
        .then(() => {
          closed = true;
        })
        .catch(() => {}),
      new Promise((done) => setTimeout(done, 5000)),
    ]);
    if (!closed) {
      await browserServer.kill();
      browserServer = await chromium.launchServer({ headless: true });
      browser = await chromium.connect(browserServer.wsEndpoint());
    }
    await openPage();
    emit({ event: "runtime_restarted", pid: browserServer.process().pid });
    const resume = await iterator.next();
    if (resume.done || JSON.parse(resume.value).command !== "resume")
      throw new Error("Restart was not verified by the owning controller");
  }
  try {
    if (runtime === "node") {
      solve = await (await import(pathToFileURL(nodeBundle).href)).nodeSolver();
      emit({ event: "ready", node: process.version, browser: null });
    } else {
      server = createServer(async (request, response) => {
        try {
          const path = resolve(
            browserDist,
            `.${new URL(request.url, "http://localhost").pathname === "/" ? "/index.html" : new URL(request.url, "http://localhost").pathname}`,
          );
          if (!path.startsWith(browserDist + sep)) throw new Error("Path outside own build");
          const types = {
            ".js": "text/javascript",
            ".html": "text/html",
            ".wasm": "application/wasm",
          };
          response.setHeader("Content-Type", types[extname(path)] ?? "application/octet-stream");
          response.end(await readFile(path));
        } catch {
          response.writeHead(404).end();
        }
      });
      await new Promise((done) => server.listen(0, "127.0.0.1", done));
      browserServer = await chromium.launchServer({ headless: true });
      browser = await chromium.connect(browserServer.wsEndpoint());
      await openPage();
      emit({
        event: "ready",
        pid: browserServer.process().pid,
        browser: browser.version(),
        node: process.version,
        execution_context: runtime === "main" ? "chromium-main" : "dedicated-worker",
      });
    }
    for (;;) {
      const item = await iterator.next();
      if (item.done) break;
      const command = JSON.parse(item.value);
      if (command.command === "finish") break;
      if (command.command === "watchdog-smoke") {
        if (!page || runtime !== "main")
          throw new Error("Watchdog smoke needs its own main-thread tab");
        const result = await guardedBrowserSolve(
          () =>
            page.evaluate(() => {
              let value = 17;
              for (;;) value = Math.imul(value, 1597334677) | 0;
            }),
          replaceOwnContext,
          100,
        );
        emit({ event: "watchdog_smoke", ...result });
      } else if (command.command === "cdp-rate") {
        if (!cdp || runtime !== "main")
          throw new Error("CDP rate requires explicit main-thread context");
        await cdp.send("Emulation.setCPUThrottlingRate", { rate: command.rate });
        currentRate = command.rate;
        emit({ event: "cdp_rate", rate: command.rate, execution_context: "chromium-main" });
      } else if (command.command === "probe") {
        if (!page) throw new Error("CPU calibration needs a browser");
        emit({
          event: "probe",
          ...(await page.evaluate(
            ({ count, repeats }) => window.deviceBenchmark.calibrate(count, repeats),
            command,
          )),
        });
      } else if (command.command === "measure") {
        const { document, members } = command.problem;
        const { modelFingerprint } = await import(pathToFileURL(nodeBundle).href);
        const models = new Map();
        let id = 0;
        for (const member of members)
          for (const window of [3, 5])
            for (let repetition = 0; repetition < command.repeats; repetition += 1) {
              const request = { id: ++id, document, entry: member.entry, window };
              const key = `${member.member}:${window}`;
              if (!models.has(key)) models.set(key, modelFingerprint(request));
              const started = performance.now();
              let result;
              try {
                if (runtime === "node") {
                  result = await solve(request);
                  result.outer_elapsed_seconds = (performance.now() - started) / 1000;
                } else
                  result = await guardedBrowserSolve(
                    () => solve(request, command.audit),
                    replaceOwnContext,
                  );
              } catch (error) {
                result = {
                  reply: { kind: "failed", status: String(error) },
                  elapsed_seconds: (performance.now() - started) / 1000,
                  outer_elapsed_seconds: (performance.now() - started) / 1000,
                };
              }
              const completed = result.reply.kind === "answer";
              emit({
                event: "sample",
                runtime,
                execution_context:
                  runtime === "node"
                    ? "node"
                    : runtime === "main"
                      ? "chromium-main"
                      : "dedicated-worker",
                purpose: command.purpose,
                expected_model_sha256: models.get(key),
                pool: command.pool,
                players: document.players.length,
                member: member.member,
                free_transfers: member.entry.free_transfers,
                window,
                repetition,
                ...result,
                completed,
                censored:
                  !completed &&
                  (result.reply.kind === "timeout" || /time/i.test(result.reply.status ?? "")),
              });
              // A diagnostic timeout terminates that worker. Do not silently skip later shapes.
            }
        emit({ event: "measured" });
      } else throw new Error("Unknown diagnostic command");
    }
  } finally {
    lines.close();
    if (cdp) await cdp.send("Emulation.setCPUThrottlingRate", { rate: 1 }).catch(() => {});
    await browser?.close();
    await browserServer?.close();
    if (server) await new Promise((done) => server.close(done));
  }
}
