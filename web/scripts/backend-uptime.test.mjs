// Execute the workflow's real script with an in-memory GitHub and no network.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const workflow = readFileSync(
  resolve(process.cwd(), "../.github/workflows/backend-uptime.yml"),
  "utf8",
).replace(/\r\n/g, "\n");
const script = workflow
  .split("          script: |\n")[1]
  ?.split("\n")
  .map((line) => line.replace(/^ {12}/, ""))
  .join("\n");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

async function run({
  event = "workflow_dispatch",
  exercise = "true",
  dryRun = "false",
  healthUrl = "",
  production = true,
  response = 200,
  readyResponse = response,
  readyBody,
  incidentBody = "Real incident",
  tamper,
  failClose = false,
  ignoreClose = false,
  failCreate = false,
  missingLabel = false,
} = {}) {
  const real = {
    number: 42,
    state: "open",
    title: "Backend health check failed",
    body: incidentBody,
    labels: [{ name: "backend-down" }],
  };
  const issues = new Map(production ? [[42, real]] : []);
  const calls = [];
  const logs = [];
  const failures = [];
  const urls = [];
  let fetches = 0;
  const api = {
    listForRepo: "listForRepo",
    getLabel: async (args) => {
      calls.push(["getLabel", args]);
      if (missingLabel) throw Object.assign(new Error("missing"), { status: 404 });
    },
    createLabel: async (args) => {
      calls.push(["createLabel", args]);
    },
    create: async (args) => {
      calls.push(["create", args]);
      if (failCreate) throw new Error("create denied");
      const issue = {
        ...args,
        number: 99,
        state: "open",
        html_url: "https://example.test/issues/99",
      };
      issues.set(99, issue);
      return { data: { ...issue } };
    },
    get: async (args) => {
      calls.push(["get", args]);
      const issue = { ...issues.get(args.issue_number) };
      return { data: tamper ? tamper(issue) : issue };
    },
    createComment: async (args) => {
      calls.push(["comment", args]);
    },
    update: async (args) => {
      calls.push(["update", args]);
      if (failClose) throw new Error("close denied");
      const changed = Object.fromEntries(
        Object.entries(args).filter(([key]) => ["state", "body"].includes(key)),
      );
      if (!ignoreClose) Object.assign(issues.get(args.issue_number), changed);
    },
  };
  const github = {
    rest: { issues: api },
    paginate: async (method, args) => {
      expect(method).toBe("listForRepo");
      calls.push(["list", args]);
      return [...issues.values()].filter(
        (issue) =>
          issue.state === "open" &&
          issue.labels.some(
            (label) => (typeof label === "string" ? label : label.name) === args.labels,
          ),
      );
    },
  };
  let error;
  try {
    await new AsyncFunction("process", "context", "github", "core", "fetch", "setTimeout", script)(
      {
        env: {
          DRY_RUN: dryRun,
          EXERCISE: exercise,
          TEST_HEALTH_URL: healthUrl,
          GITHUB_RUN_ATTEMPT: "2",
        },
      },
      {
        eventName: event,
        repo: { owner: "fixture", repo: "fixture" },
        runId: 123,
        serverUrl: "https://example.test",
      },
      github,
      { info: (line) => logs.push(line), setFailed: (line) => failures.push(line) },
      async (url) => {
        fetches += 1;
        urls.push(String(url));
        const ready = String(url).endsWith("/ready");
        const status = ready ? readyResponse : response;
        const body =
          ready && readyBody === undefined
            ? JSON.stringify({
                ready: status === 200,
                checks: { worker_heartbeat: status === 200 },
              })
            : (readyBody ?? "{}");
        return { status, text: async () => body, body: { cancel: async () => {} } };
      },
      (callback) => callback(),
    );
  } catch (caught) {
    error = caught;
  }
  return { issues, calls, logs, failures, fetches, urls, error };
}

describe("backend alarm issue exercise", () => {
  it("is explicitly opt-in and unreachable from schedule even with a forged environment input", async () => {
    expect(workflow).toContain(
      "EXERCISE: ${{ github.event_name == 'workflow_dispatch' && inputs.exercise == true }}",
    );
    expect(workflow).toMatch(/exercise:\s+description:[^\n]+\n\s+type: boolean\n\s+default: false/);
    const result = await run({ event: "schedule", exercise: "true", production: false });
    expect(result.error).toBeUndefined();
    expect(result.fetches).toBe(2);
    expect(result.urls).toEqual([
      "https://squadopt-api.mymandev.com/health",
      "https://squadopt-api.mymandev.com/ready",
    ]);
    expect(result.calls.filter(([kind]) => kind === "create")).toEqual([]);
    expect(result.calls.find(([kind]) => kind === "list")[1].labels).toBe("backend-down");
  });

  it("opens and closes its own marked exercise while an existing production incident stays open", async () => {
    const result = await run({ missingLabel: true });
    expect(result.error).toBeUndefined();
    expect(result.failures).toEqual([]);
    expect(result.fetches).toBe(0);
    expect(result.issues.get(42).state).toBe("open");
    expect(result.issues.get(99).state).toBe("closed");
    const issue = result.issues.get(99);
    expect(issue.title).toMatch(/^\[EXERCISE\]/);
    expect(issue.labels).toEqual(["backend-uptime-exercise"]);
    expect(issue.body.split("\n")[0]).toMatch(/^EXERCISE run 123, attempt 2 at \d{4}-.*Z\.$/);
    expect(issue.body).toContain("/actions/runs/123");
    expect(result.calls.some(([kind]) => kind === "list")).toBe(false);
    for (const [kind, args] of result.calls) {
      if (["get", "comment", "update"].includes(kind)) expect(args.issue_number).toBe(99);
    }
    expect(result.calls.find(([kind]) => kind === "comment")[1].body).toContain(
      "synthetic healthy recovery",
    );
    expect(result.logs).toContain("Exercise issue created: https://example.test/issues/99");
    expect(result.logs).toContain("Exercise issue closed: https://example.test/issues/99");
  });

  it("accepts GitHub CRLF body storage without weakening exercise ownership", async () => {
    const result = await run({
      tamper: (issue) => ({ ...issue, body: issue.body.replace(/\r?\n/g, "\r\n") }),
    });
    expect(result.error).toBeUndefined();
    expect(result.failures).toEqual([]);
    expect(result.fetches).toBe(0);
    expect(result.issues.get(99).state).toBe("closed");
    expect(result.issues.get(42).state).toBe("open");
    expect(result.calls.some(([kind]) => kind === "list")).toBe(false);
    expect(result.logs).toContain("Exercise issue closed: https://example.test/issues/99");
  });

  it.each([
    ["different number", (issue) => ({ ...issue, number: 42 })],
    ["production label", (issue) => ({ ...issue, labels: ["backend-down"] })],
    ["both labels", (issue) => ({ ...issue, labels: ["backend-down", "backend-uptime-exercise"] })],
    ["different run", (issue) => ({ ...issue, body: "EXERCISE run 456" })],
    ["unmarked title", (issue) => ({ ...issue, title: "Real alarm" })],
    [
      "different run title",
      (issue) => ({ ...issue, title: "[EXERCISE] Backend alarm permission, run 456" }),
    ],
    ["pull request", (issue) => ({ ...issue, pull_request: {} })],
  ])("refuses to close a retrieved issue with %s", async (_name, tamper) => {
    const result = await run({ tamper });
    expect(result.error?.message).toContain("Refusing to close");
    expect(result.calls.some(([kind]) => kind === "update")).toBe(false);
    expect(result.issues.get(42).state).toBe("open");
  });

  it.each([{ failClose: true }, { ignoreClose: true }])(
    "fails loudly when closure fails: %j",
    async (options) => {
      const result = await run(options);
      expect(result.error).toBeInstanceOf(Error);
      expect(result.issues.get(99).state).toBe("open");
      expect(result.issues.get(42).state).toBe("open");
      expect(result.logs.some((line) => line.startsWith("Exercise issue closed"))).toBe(false);
    },
  );

  it("does not attempt recovery after a denied create", async () => {
    const result = await run({ failCreate: true });
    expect(result.error?.message).toBe("create denied");
    expect(result.calls.some(([kind]) => ["get", "comment", "update"].includes(kind))).toBe(false);
  });

  it.each([{ dryRun: "true" }, { healthUrl: "https://example.test/health" }])(
    "rejects ambiguous exercise inputs: %j",
    async (options) => {
      const result = await run(options);
      expect(result.failures).toHaveLength(1);
      expect(result.fetches).toBe(0);
      expect(result.calls).toEqual([]);
    },
  );

  it("keeps the ordinary production failed probe and recovery transitions", async () => {
    const down = await run({
      event: "schedule",
      exercise: "false",
      production: false,
      response: 503,
    });
    expect(down.error).toBeUndefined();
    expect(down.fetches).toBe(4);
    expect(down.issues.get(99).labels).toEqual(["backend-down"]);
    expect(down.issues.get(99).state).toBe("open");
    const up = await run({ event: "schedule", exercise: "false" });
    expect(up.error).toBeUndefined();
    expect(up.issues.get(42).state).toBe("closed");
    const dry = await run({ exercise: "false", dryRun: "true" });
    expect(dry.issues.get(42).state).toBe("open");
  });
});

describe("backend readiness probe", () => {
  const notReady = JSON.stringify({
    ready: false,
    checks: {
      capture_context: true,
      worker_heartbeat: false,
      "C:/store/workers": false,
      queue_wait: false,
    },
    detail: "a body the issue must not carry",
  });

  it("opens the backend-down incident naming only the false checks while health still answers", async () => {
    const result = await run({
      event: "schedule",
      exercise: "false",
      production: false,
      readyResponse: 503,
      readyBody: notReady,
    });
    expect(result.error).toBeUndefined();
    expect(result.fetches).toBe(4);
    const issue = result.issues.get(99);
    expect(issue.labels).toEqual(["backend-down"]);
    expect(issue.title).toBe("Backend health or readiness check failed");
    expect(issue.body).toContain("Failing: ready (HTTP 503, false: worker_heartbeat, queue_wait).");
    expect(issue.body).toContain("health HTTP 200");
    for (const leak of ["C:/store", "must not carry", "https://", "mymandev"]) {
      expect(issue.body).not.toContain(leak);
    }
  });

  it("records a continuing failure only when what fails changes", async () => {
    const changed = await run({
      event: "schedule",
      exercise: "false",
      readyResponse: 503,
      readyBody: notReady,
    });
    expect(changed.error).toBeUndefined();
    const comments = changed.calls.filter(([kind]) => kind === "comment");
    expect(comments).toHaveLength(1);
    expect(comments[0][1].issue_number).toBe(42);
    expect(comments[0][1].body).toContain("false: worker_heartbeat, queue_wait");
    const incident = changed.issues.get(42);
    expect(incident.state).toBe("open");
    expect(incident.body).toBe(
      "Real incident\nFailing: ready (HTTP 503, false: worker_heartbeat, queue_wait).",
    );
    expect(changed.issues.has(99)).toBe(false);

    const same = await run({
      event: "schedule",
      exercise: "false",
      readyResponse: 503,
      readyBody: notReady,
      incidentBody: incident.body.replace(/\n/g, "\r\n"),
    });
    expect(same.error).toBeUndefined();
    expect(same.calls.some(([kind]) => ["comment", "update", "create"].includes(kind))).toBe(false);
    expect(same.logs.some((line) => line.startsWith("Check: no change;"))).toBe(true);
  });

  it("does not take a 200 that never says ready as ready", async () => {
    const result = await run({
      event: "schedule",
      exercise: "false",
      production: false,
      readyBody: "not json",
    });
    expect(result.issues.get(99).body).toContain("Failing: ready (HTTP 200 without ready: true).");
  });

  it("probes the ready URL beside a dry run's test health URL", async () => {
    const result = await run({
      exercise: "false",
      dryRun: "true",
      production: false,
      healthUrl: "https://example.test/base/health",
      readyResponse: 503,
      readyBody: notReady,
    });
    expect(result.error).toBeUndefined();
    expect(result.urls.slice(0, 2)).toEqual([
      "https://example.test/base/health",
      "https://example.test/base/ready",
    ]);
    expect(result.calls.some(([kind]) => ["comment", "update", "create"].includes(kind))).toBe(
      false,
    );
    expect(result.logs.some((line) => line.startsWith("Dry run: would open incident;"))).toBe(true);
  });
});
