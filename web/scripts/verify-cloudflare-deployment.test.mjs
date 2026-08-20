import { describe, expect, it } from "vitest";

import { verifyDeploymentRecord } from "./verify-cloudflare-deployment.mjs";

const commitSha = "a".repeat(40);
const deploymentId = "f64788e9-fccd-4d4a-a28a-cb84f88f6";
const valid = {
  id: deploymentId,
  project_name: "squadopt",
  environment: "production",
  latest_stage: { status: "success" },
  deployment_trigger: { metadata: { branch: "main", commit_hash: commitSha } },
  aliases: ["https://squadopt.pages.dev"],
};

const expected = {
  deploymentId,
  project: "squadopt",
  mode: "production",
  branch: "main",
  commitSha,
  alias: "https://squadopt.pages.dev",
};

describe("Cloudflare deployment identity", () => {
  it("accepts an exact successful production deployment", () => {
    expect(() => verifyDeploymentRecord({ deployment: valid, ...expected })).not.toThrow();
  });

  it.each([
    ["environment", { ...valid, environment: "preview" }],
    [
      "commit",
      {
        ...valid,
        deployment_trigger: {
          metadata: { branch: "main", commit_hash: "b".repeat(40) },
        },
      },
    ],
    ["alias", { ...valid, aliases: ["https://main.squadopt.pages.dev"] }],
    ["status", { ...valid, latest_stage: { status: "failure" } }],
  ])("rejects a mismatched %s", (_name, deployment) => {
    expect(() => verifyDeploymentRecord({ deployment, ...expected })).toThrow();
  });
});
