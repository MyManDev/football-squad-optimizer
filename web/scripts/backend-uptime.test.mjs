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
    body: "Real incident",
    labels: [{ name: "backend-down" }],
  };
  const issues = new Map(production ? [[42, real]] : []);
  const calls = [];
  const logs = [];
  const failures = [];
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
      if (!ignoreClose) Object.assign(issues.get(args.issue_number), { state: args.state });
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
      async () => {
        fetches += 1;
        return { status: response, body: { cancel: async () => {} } };
      },
      (callback) => callback(),
    );
  } catch (caught) {
    error = caught;
  }
  return { issues, calls, logs, failures, fetches, error };
}

describe("backend alarm issue exercise", () => {
  it("is explicitly opt-in and unreachable from schedule even with a forged environment input", async () => {
    expect(workflow).toContain(
      "EXERCISE: ${{ github.event_name == 'workflow_dispatch' && inputs.exercise == true }}",
    );
    expect(workflow).toMatch(/exercise:\s+description:[^\n]+\n\s+type: boolean\n\s+default: false/);
    const result = await run({ event: "schedule", exercise: "true", production: false });
    expect(result.error).toBeUndefined();
    expect(result.fetches).toBe(1);
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

  it.each([
    ["different number", (issue) => ({ ...issue, number: 42 })],
    ["production label", (issue) => ({ ...issue, labels: ["backend-down"] })],
    ["both labels", (issue) => ({ ...issue, labels: ["backend-down", "backend-uptime-exercise"] })],
    ["different run", (issue) => ({ ...issue, body: "EXERCISE run 456" })],
    ["unmarked title", (issue) => ({ ...issue, title: "Real alarm" })],
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
    expect(down.fetches).toBe(2);
    expect(down.issues.get(99).labels).toEqual(["backend-down"]);
    expect(down.issues.get(99).state).toBe("open");
    const up = await run({ event: "schedule", exercise: "false" });
    expect(up.error).toBeUndefined();
    expect(up.issues.get(42).state).toBe("closed");
    const dry = await run({ exercise: "false", dryRun: "true" });
    expect(dry.issues.get(42).state).toBe("open");
  });
});
