/** Only this owned launcher and its browser descendants enter the temporary CPU job. */
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createInterface } from "node:readline";

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
  let server, browserServer, browser, page, solve;
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
      page = await browser.newPage();
      await page.goto(`http://127.0.0.1:${server.address().port}`);
      await page.waitForFunction(() => !!window.deviceBenchmark);
      await page.evaluate(() => window.deviceBenchmark.ready());
      solve = (request) => page.evaluate((value) => window.deviceBenchmark.solve(value), request);
      emit({
        event: "ready",
        pid: browserServer.process().pid,
        browser: browser.version(),
        node: process.version,
      });
    }
    for (;;) {
      const item = await iterator.next();
      if (item.done) break;
      const command = JSON.parse(item.value);
      if (command.command === "finish") break;
      if (command.command === "probe") {
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
        let id = 0;
        for (const member of members)
          for (const window of [3, 5])
            for (let repetition = 0; repetition < command.repeats; repetition += 1) {
              const request = { id: ++id, document, entry: member.entry, window };
              const started = performance.now();
              let result;
              try {
                result = await solve(request);
              } catch (error) {
                result = {
                  reply: { kind: "failed", status: String(error) },
                  elapsed_seconds: (performance.now() - started) / 1000,
                };
              }
              const completed = result.reply.kind === "answer";
              emit({
                event: "sample",
                runtime,
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
              if (result.reply.kind === "timeout" && page) {
                await page.reload();
                await page.waitForFunction(() => !!window.deviceBenchmark);
                await page.evaluate(() => window.deviceBenchmark.ready());
              }
            }
        emit({ event: "measured" });
      } else throw new Error("Unknown diagnostic command");
    }
  } finally {
    lines.close();
    await browser?.close();
    await browserServer?.close();
    if (server) await new Promise((done) => server.close(done));
  }
}
