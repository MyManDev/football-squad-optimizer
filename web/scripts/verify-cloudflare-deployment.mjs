import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

import { parseApiResponse } from "./cloudflare-deployment-budget.mjs";

const delay = (milliseconds) =>
  new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

function requiredEnvironment(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function normalizedUrl(value) {
  const url = new URL(value);
  if (url.protocol !== "https:") throw new Error(`Expected an HTTPS alias, got ${value}`);
  return url.href.replace(/\/$/, "").toLowerCase();
}

// The aliases a deployment may legitimately own, from a comma-separated list or an array.
// Empty is refused rather than defaulted: a verification with nothing to compare against
// would pass every deployment.
export function expectedAliasSet(value) {
  const candidates = (typeof value === "string" ? value.split(",") : [...(value ?? [])])
    .map((candidate) => String(candidate).trim())
    .filter((candidate) => candidate.length > 0);
  if (candidates.length === 0) {
    throw new Error("At least one expected deployment alias is required");
  }
  return new Set(candidates.map((candidate) => normalizedUrl(candidate)));
}

export function verifyDeploymentRecord({
  deployment,
  deploymentId,
  project,
  mode,
  branch,
  commitSha,
  aliases,
}) {
  if (deployment?.id !== deploymentId) throw new Error("Cloudflare deployment ID mismatch");
  if (deployment?.project_name !== project) throw new Error("Cloudflare project name mismatch");
  if (deployment?.environment !== mode) {
    throw new Error(`Cloudflare deployment environment is ${deployment?.environment}, not ${mode}`);
  }
  if (deployment?.latest_stage?.status !== "success") {
    throw new Error(
      `Cloudflare deployment status is ${deployment?.latest_stage?.status ?? "missing"}, not success`,
    );
  }
  if (deployment?.deployment_trigger?.metadata?.branch !== branch) {
    throw new Error("Cloudflare deployment branch mismatch");
  }
  if (deployment?.deployment_trigger?.metadata?.commit_hash?.toLowerCase() !== commitSha) {
    throw new Error("Cloudflare deployment commit SHA mismatch");
  }

  // Any one of the project's canonical aliases, not one specific alias. When a custom
  // domain is attached, a production deployment's ``aliases`` array carries that domain and
  // not the apex ``*.pages.dev`` hostname, so requiring the subdomain asserted something the
  // API does not report. Owning none of them is still a rejection.
  const expected = expectedAliasSet(aliases);
  const owned = Array.isArray(deployment?.aliases)
    ? deployment.aliases.map((candidate) => normalizedUrl(candidate))
    : [];
  const matched = owned.find((candidate) => expected.has(candidate));
  if (matched === undefined) {
    throw new Error(
      `Cloudflare deployment owns none of the expected aliases ${[...expected].join(", ")}`,
    );
  }
  return matched;
}

async function getDeployment({ accountId, project, deploymentId, apiToken }) {
  const url = new URL(
    `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/pages/projects/${encodeURIComponent(project)}/deployments/${encodeURIComponent(deploymentId)}`,
  );
  const response = await fetch(url, {
    headers: { authorization: `Bearer ${apiToken}` },
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await parseApiResponse(response);
  if (!payload.result || typeof payload.result !== "object" || Array.isArray(payload.result)) {
    throw new Error("Cloudflare Pages API response does not contain a deployment");
  }
  return payload.result;
}

function safeMessage(error) {
  return String(error instanceof Error ? error.message : error)
    .replace(/[\r\n]+/g, " ")
    .slice(0, 300);
}

async function main() {
  const apiToken = requiredEnvironment("CLOUDFLARE_API_TOKEN");
  const accountId = requiredEnvironment("CLOUDFLARE_ACCOUNT_ID");
  const project = requiredEnvironment("CLOUDFLARE_PAGES_PROJECT");
  const deploymentId = requiredEnvironment("CLOUDFLARE_DEPLOYMENT_ID");
  const mode = requiredEnvironment("EXPECTED_DEPLOYMENT_MODE");
  const branch = requiredEnvironment("EXPECTED_DEPLOYMENT_BRANCH");
  const commitSha = requiredEnvironment("EXPECTED_DEPLOYMENT_COMMIT_SHA").toLowerCase();
  const aliases = expectedAliasSet(requiredEnvironment("EXPECTED_DEPLOYMENT_ALIASES"));
  const actionEnvironment = requiredEnvironment("ACTION_PAGES_ENVIRONMENT");

  if (!/^[0-9a-f]{32}$/i.test(accountId)) throw new Error("Invalid Cloudflare account ID");
  if (!/^[a-z0-9](?:[a-z0-9-]{0,56}[a-z0-9])?$/.test(project)) {
    throw new Error("Invalid Cloudflare Pages project name");
  }
  if (!/^[0-9a-f-]{36}$/i.test(deploymentId)) throw new Error("Invalid deployment ID");
  if (!new Set(["preview", "production"]).has(mode)) throw new Error("Invalid deployment mode");
  if (!/^[A-Za-z0-9._/-]+$/.test(branch)) throw new Error("Invalid deployment branch");
  if (!/^[0-9a-f]{40}$/.test(commitSha)) throw new Error("Invalid deployment commit SHA");
  if (actionEnvironment !== mode) {
    throw new Error(`Wrangler reported ${actionEnvironment}, expected ${mode}`);
  }

  let lastError;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      const deployment = await getDeployment({ accountId, project, deploymentId, apiToken });
      const matched = verifyDeploymentRecord({
        deployment,
        deploymentId,
        project,
        mode,
        branch,
        commitSha,
        aliases,
      });
      console.log(
        `Verified Cloudflare deployment ${deploymentId}: ${mode} ${branch} ${commitSha} -> ${matched}`,
      );
      return;
    } catch (error) {
      lastError = error;
      if (attempt < 5) {
        console.warn(`Deployment metadata not ready (attempt ${attempt}): ${safeMessage(error)}`);
        await delay(Math.min(2 ** attempt * 1_000, 10_000));
      }
    }
  }
  throw new Error("Cloudflare deployment identity verification failed", { cause: lastError });
}

const entryPoint = process.argv[1] ? resolve(process.argv[1]) : "";
if (entryPoint === fileURLToPath(import.meta.url)) {
  await main();
}
