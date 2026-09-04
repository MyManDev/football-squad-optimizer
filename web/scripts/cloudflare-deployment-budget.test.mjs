import { describe, expect, it } from "vitest";

import {
  DAILY_DEPLOYMENT_LIMIT,
  PREVIEW_DEPLOYMENT_LIMIT,
  deploymentDecision,
  listDeployments,
  utcDayBounds,
  validateProjectConfiguration,
  validatedPagesSubdomain,
} from "./cloudflare-deployment-budget.mjs";

const now = new Date("2026-08-20T17:30:00.000Z");

function deployment({
  createdOn = "2026-08-20T12:00:00.000Z",
  environment = "preview",
  branch = "pr-123",
  commitSha = "a".repeat(40),
  status = "success",
  url = "https://example.pages.dev",
} = {}) {
  return {
    created_on: createdOn,
    environment,
    latest_stage: { status },
    deployment_trigger: { metadata: { branch, commit_hash: commitSha } },
    url,
  };
}

describe("Cloudflare deployment budget", () => {
  it("uses UTC calendar-day boundaries", () => {
    const { start, end } = utcDayBounds(now);
    expect(start.toISOString()).toBe("2026-08-20T00:00:00.000Z");
    expect(end.toISOString()).toBe("2026-08-21T00:00:00.000Z");
  });

  it("accepts only a Cloudflare Pages project hostname", () => {
    expect(validatedPagesSubdomain("SquadOpt-Euo.pages.dev")).toBe("squadopt-euo.pages.dev");
    expect(() => validatedPagesSubdomain("squadopt.example.com")).toThrow(
      "invalid project subdomain",
    );
  });

  it("requires a main-branch Direct Upload project", () => {
    expect(
      validateProjectConfiguration({
        production_branch: "main",
        source: null,
        subdomain: "squadopt.pages.dev",
      }),
    ).toBe("squadopt.pages.dev");
    expect(() =>
      validateProjectConfiguration({
        production_branch: "main",
        source: { type: "github" },
        subdomain: "squadopt.pages.dev",
      }),
    ).toThrow("Direct Upload");
  });

  it("reserves two daily slots by stopping previews at eight", () => {
    const deployments = Array.from({ length: PREVIEW_DEPLOYMENT_LIMIT }, (_, index) =>
      deployment({ commitSha: index.toString(16).padStart(40, "0") }),
    );
    expect(
      deploymentDecision({
        deployments,
        mode: "preview",
        now,
      }),
    ).toMatchObject({ decision: "blocked", todayCount: 8 });
  });

  it("allows production through slot ten but blocks an eleventh deployment", () => {
    const firstNine = Array.from({ length: DAILY_DEPLOYMENT_LIMIT - 1 }, (_, index) =>
      deployment({ commitSha: index.toString(16).padStart(40, "0") }),
    );
    const request = {
      mode: "production",
      now,
    };
    expect(deploymentDecision({ deployments: firstNine, ...request }).decision).toBe("deploy");
    expect(
      deploymentDecision({
        deployments: [...firstNine, deployment({ commitSha: "e".repeat(40) })],
        ...request,
      }).decision,
    ).toBe("blocked");
  });

  it("counts failed deployments", () => {
    const failed = deployment({ status: "failure" });
    const request = {
      mode: "preview",
      now,
    };

    expect(deploymentDecision({ deployments: [failed], ...request })).toMatchObject({
      decision: "deploy",
      todayCount: 1,
    });
  });

  it("does not count deployments outside the current UTC day", () => {
    const deployments = [
      deployment({ createdOn: "2026-08-19T23:59:59.999Z" }),
      deployment({ createdOn: "2026-08-21T00:00:00.000Z" }),
    ];
    const result = deploymentDecision({
      deployments,
      mode: "preview",
      now,
    });
    expect(result).toMatchObject({ decision: "deploy", todayCount: 0 });
  });

  it("accepts an empty project whose API reports zero pages", async () => {
    const deployments = await listDeployments({
      accountId: "a".repeat(32),
      project: "squadopt",
      apiToken: "secret",
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          result: [],
          result_info: { page: 1, total_pages: 0 },
        }),
      }),
    });
    expect(deployments).toEqual([]);
  });
});
