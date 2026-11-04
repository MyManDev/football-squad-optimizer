import { readFileSync } from "node:fs";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const workflow = readFileSync(
  resolvePath(dirname(fileURLToPath(import.meta.url)), "../../.github/workflows/deploy-pages.yml"),
  "utf8",
).replace(/\r\n/g, "\n");
const job = workflow.split("  production_meta:\n")[1].split("\n  production:\n")[0];
const script = job
  .split("          script: |\n")[1]
  .split("\n")
  .map((line) => (line.startsWith("            ") ? line.slice(12) : line))
  .join("\n");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const commitSha = "a".repeat(40);
const tag = "site-2026-27-gw10-fix2";
const successful = {
  id: 123,
  head_sha: commitSha,
  head_branch: "main",
  event: "push",
  status: "completed",
  conclusion: "success",
  path: ".github/workflows/ci.yml",
};

async function resolve({
  runs = [successful],
  artifacts = [{ name: "site", expired: false }],
  refType = "tag",
  ancestry = "identical",
} = {}) {
  const errors = [];
  const outputs = {};
  const requests = [];
  const listWorkflowRuns = Symbol("runs");
  const listWorkflowRunArtifacts = Symbol("artifacts");
  const summary = {
    addHeading() {
      return this;
    },
    addRaw() {
      return this;
    },
    write() {},
  };
  const core = {
    setFailed: (message) => errors.push(message),
    setOutput: (name, value) => {
      outputs[name] = value;
    },
    summary,
  };
  const github = {
    rest: {
      git: {
        getRef: async () => ({ data: { object: { type: refType, sha: "annotated-tag" } } }),
        getTag: async () => ({ data: { object: { type: "commit", sha: commitSha } } }),
      },
      repos: { compareCommits: async () => ({ data: { status: ancestry } }) },
      actions: { listWorkflowRuns, listWorkflowRunArtifacts },
    },
    paginate: async (endpoint, params) => {
      requests.push({ endpoint, params });
      if (endpoint === listWorkflowRuns) {
        // The filtered index can lag behind the completed run's own record.
        return params.status ? [] : runs;
      }
      expect(endpoint).toBe(listWorkflowRunArtifacts);
      return artifacts;
    },
  };
  await new AsyncFunction("github", "core", "context", "process", script)(
    github,
    core,
    { repo: { owner: "example", repo: "site" } },
    { env: { RELEASE_TAG: tag } },
  );
  return { errors, outputs, requests };
}

describe("production source resolution", () => {
  it("accepts the completed successful main run while the status-filtered index is stale", async () => {
    const result = await resolve();
    expect(result.errors).toEqual([]);
    expect(result.outputs).toEqual({ ci_run_id: "123", commit_sha: commitSha, release_tag: tag });
  });

  it.each([
    ["pending", { status: "in_progress" }],
    ["failed", { conclusion: "failure" }],
    ["cancelled", { conclusion: "cancelled" }],
    ["another commit", { head_sha: "b".repeat(40) }],
    ["another branch", { head_branch: "develop" }],
    ["a pull request", { event: "pull_request" }],
    ["another workflow", { path: ".github/workflows/other.yml" }],
  ])("refuses %s runs before reading their artifacts", async (_name, override) => {
    const result = await resolve({ runs: [{ ...successful, ...override }] });
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toMatch(/No successful main-push CI/);
    expect(result.outputs).toEqual({});
    expect(result.requests).toHaveLength(1);
  });

  it("selects the newest valid run, excluding a newer failed run", async () => {
    const result = await resolve({
      runs: [
        { ...successful, id: 124 },
        { ...successful, id: 126, conclusion: "failure" },
        { ...successful, id: 125 },
      ],
    });
    expect(result.errors).toEqual([]);
    expect(result.outputs.ci_run_id).toBe("125");
    expect(result.requests[1].params.run_id).toBe(125);
  });

  it.each([
    ["missing", []],
    ["expired", [{ name: "site", expired: true }]],
    [
      "duplicate",
      [
        { name: "site", expired: false },
        { name: "site", expired: false },
      ],
    ],
  ])("refuses a %s site artifact", async (_name, artifacts) => {
    const result = await resolve({ artifacts });
    expect(result.errors[0]).toMatch(/exactly one unexpired site artifact/);
    expect(result.outputs).toEqual({});
  });

  it("still requires an annotated tag", async () => {
    const result = await resolve({ refType: "commit" });
    expect(result.errors[0]).toMatch(/must be annotated/);
    expect(result.requests).toEqual([]);
  });

  it("still requires the tagged commit to belong to main", async () => {
    const result = await resolve({ ancestry: "diverged" });
    expect(result.errors[0]).toMatch(/not reachable from main/);
    expect(result.requests).toEqual([]);
  });
});
