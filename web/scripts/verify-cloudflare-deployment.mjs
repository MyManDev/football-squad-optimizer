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

export function verifyDeploymentRecord({
  deployment,
  deploymentId,
  project,
  mode,
  branch,
  commitSha,
  alias,
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

  const expectedAlias = normalizedUrl(alias);
  const aliases = Array.isArray(deployment?.aliases)
    ? deployment.aliases.map((candidate) => normalizedUrl(candidate))
    : [];
  if (!aliases.includes(expectedAlias)) {
    throw new Error(`Cloudflare deployment does not own expected alias ${expectedAlias}`);
  }
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
  const alias = requiredEnvironment("EXPECTED_DEPLOYMENT_ALIAS");
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
      verifyDeploymentRecord({
        deployment,
        deploymentId,
        project,
        mode,
        branch,
        commitSha,
        alias,
      });
      console.log(
        `Verified Cloudflare deployment ${deploymentId}: ${mode} ${branch} ${commitSha} -> ${alias}`,
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
