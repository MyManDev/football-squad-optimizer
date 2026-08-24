import { describe, expect, it } from "vitest";

import { expectedAliasSet, verifyDeploymentRecord } from "./verify-cloudflare-deployment.mjs";

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
  aliases: "https://squadopt.pages.dev",
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

// A project with a custom domain attached reports that domain in a production deployment's
// ``aliases`` and never the apex ``*.pages.dev`` hostname. Asserting the subdomain alone
// failed two real production dispatches after a successful upload (#222).
describe("Cloudflare deployment identity across the project's canonical aliases", () => {
  const canonical = "https://squadopt.pages.dev,https://squadopt.com";

  it("accepts a deployment owning the attached custom domain rather than the apex", () => {
    expect(
      verifyDeploymentRecord({
        deployment: { ...valid, aliases: ["https://squadopt.com"] },
        ...expected,
        aliases: canonical,
      }),
    ).toBe("https://squadopt.com");
  });

  it("still accepts a deployment owning the pages.dev apex", () => {
    expect(verifyDeploymentRecord({ deployment: valid, ...expected, aliases: canonical })).toBe(
      "https://squadopt.pages.dev",
    );
  });

  it("rejects a deployment owning none of the canonical aliases", () => {
    expect(() =>
      verifyDeploymentRecord({
        deployment: { ...valid, aliases: ["https://pr-7.squadopt.pages.dev"] },
        ...expected,
        aliases: canonical,
      }),
    ).toThrow("owns none of the expected aliases");
  });

  it("rejects a deployment carrying no aliases at all", () => {
    expect(() =>
      verifyDeploymentRecord({
        deployment: { ...valid, aliases: [] },
        ...expected,
        aliases: canonical,
      }),
    ).toThrow("owns none of the expected aliases");
  });

  it("refuses an empty expected set rather than passing everything", () => {
    expect(() => expectedAliasSet("")).toThrow("At least one expected deployment alias");
    expect(() => expectedAliasSet([])).toThrow("At least one expected deployment alias");
  });

  it("reads a comma-separated list, an array or its own output", () => {
    const fromString = expectedAliasSet(canonical);
    expect([...fromString]).toEqual(["https://squadopt.pages.dev", "https://squadopt.com"]);
    expect([...expectedAliasSet(fromString)]).toEqual([...fromString]);
    expect([...expectedAliasSet([" https://Squadopt.COM/ "])]).toEqual(["https://squadopt.com"]);
  });

  it("refuses a non-https expected alias", () => {
    expect(() => expectedAliasSet("http://squadopt.com")).toThrow("Expected an HTTPS alias");
  });
});
