import { describe, expect, it } from "vitest";

import {
  verifyCanonicalDeployment,
  verifyDeploymentRecord,
  verifyPreviewAlias,
} from "./verify-cloudflare-deployment.mjs";

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
    ["status", { ...valid, latest_stage: { status: "failure" } }],
    ["id", { ...valid, id: "0000ffff-0000-0000-0000-000000000000" }],
    ["project", { ...valid, project_name: "other" }],
  ])("rejects a mismatched %s", (_name, deployment) => {
    expect(() => verifyDeploymentRecord({ deployment, ...expected })).toThrow();
  });

  it("says nothing about hostnames", () => {
    // The record check is shared by both modes, and what a deployment is reachable at is not.
    const noAliases = { ...valid, aliases: [] };
    expect(() => verifyDeploymentRecord({ deployment: noAliases, ...expected })).not.toThrow();
  });
});

// Preview deployments own their branch alias and the API reports it — confirmed by real runs
// (Actions 32717643420, 32723509231), not assumed.
describe("preview alias", () => {
  const preview = {
    ...valid,
    environment: "preview",
    aliases: ["https://pr-7.squadopt.pages.dev"],
  };

  it("accepts the branch alias the deployment owns", () => {
    expect(verifyPreviewAlias(preview, "https://pr-7.squadopt.pages.dev")).toBe(
      "https://pr-7.squadopt.pages.dev",
    );
  });

  it("normalises case and a trailing slash before comparing", () => {
    expect(verifyPreviewAlias(preview, "https://PR-7.SquadOpt.pages.dev/")).toBe(
      "https://pr-7.squadopt.pages.dev",
    );
  });

  it.each([
    ["a different pull request", { ...preview, aliases: ["https://pr-9.squadopt.pages.dev"] }],
    ["no aliases at all", { ...preview, aliases: [] }],
    ["a missing aliases field", { ...preview, aliases: undefined }],
  ])("rejects %s", (_name, deployment) => {
    expect(() => verifyPreviewAlias(deployment, "https://pr-7.squadopt.pages.dev")).toThrow(
      "does not own expected alias",
    );
  });

  it("refuses a non-https expectation", () => {
    expect(() => verifyPreviewAlias(preview, "http://pr-7.squadopt.pages.dev")).toThrow(
      "Expected an HTTPS alias",
    );
  });
});

// Production is a different question: the apex is the project's canonical hostname, not a
// per-deployment alias. Asserting the alias failed three dispatches after a successful upload
// (#222) on a project with no custom domain attached.
describe("production canonical deployment", () => {
  it("accepts the project whose canonical deployment is this one", () => {
    const project = { canonical_deployment: { id: deploymentId } };
    expect(verifyCanonicalDeployment(project, deploymentId)).toBe(deploymentId);
  });

  it("rejects a project still serving a previous deployment", () => {
    const project = { canonical_deployment: { id: "0000ffff-0000-0000-0000-000000000000" } };
    expect(() => verifyCanonicalDeployment(project, deploymentId)).toThrow(
      "canonical deployment is 0000ffff-0000-0000-0000-000000000000",
    );
  });

  it.each([
    ["no canonical_deployment", {}],
    ["a null canonical_deployment", { canonical_deployment: null }],
    ["a canonical_deployment without an id", { canonical_deployment: {} }],
    ["an empty id", { canonical_deployment: { id: "" } }],
  ])("refuses to pass when the project reports %s", (_name, project) => {
    // Silence here would be the original bug in a new place: an unverifiable claim reported
    // as verified.
    expect(() => verifyCanonicalDeployment(project, deploymentId)).toThrow(
      "reports no canonical_deployment.id",
    );
  });
});
