import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

import { getProject, listDeployments, parseApiResponse } from "./cloudflare-deployment-budget.mjs";

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

/**
 * The identity claims that hold for every deployment, whatever it is for.
 *
 * Deliberately says nothing about hostnames. What a deployment is reachable at differs
 * between preview and production in a way that is not a detail — see the two functions below.
 */
export function verifyDeploymentRecord({
  deployment,
  deploymentId,
  project,
  mode,
  branch,
  commitSha,
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
}

/**
 * A preview deployment owns its branch alias, and the API says so.
 *
 * This is not an assumption: `Verify preview deployment identity` has passed on real preview
 * runs (for example Actions runs 32717643420 and 32723509231), so `aliases` demonstrably
 * carries `https://pr-<n>.<project>.pages.dev`.
 */
export function verifyPreviewAlias(deployment, alias) {
  const expected = normalizedUrl(alias);
  const owned = Array.isArray(deployment?.aliases)
    ? deployment.aliases.map((candidate) => normalizedUrl(candidate))
    : [];
  if (!owned.includes(expected)) {
    throw new Error(`Cloudflare preview deployment does not own expected alias ${expected}`);
  }
  return expected;
}

/**
 * A production deployment is the one the apex serves, and the project says which that is.
 *
 * The apex `<project>.pages.dev` is the project's canonical hostname, not a per-deployment
 * alias, so it never appears in a production deployment's `aliases`. Asserting that it did is
 * what failed three production dispatches (#222) after a successful upload. The claim worth
 * making is the one the API actually answers: the project's canonical deployment is this one.
 */
export function verifyCanonicalDeployment(project, deploymentId) {
  const canonical = project?.canonical_deployment?.id;
  if (typeof canonical !== "string" || canonical.length === 0) {
    throw new Error(
      "Cloudflare Pages project reports no canonical_deployment.id, so which deployment the " +
        "production hostname serves cannot be verified",
    );
  }
  if (canonical !== deploymentId) {
    throw new Error(
      `Cloudflare project's canonical deployment is ${canonical}, not ${deploymentId}`,
    );
  }
  return canonical;
}

async function getDeployment({ accountId, project, deploymentId, apiToken, fetchImpl = fetch }) {
  const url = new URL(
    `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/pages/projects/${encodeURIComponent(project)}/deployments/${encodeURIComponent(deploymentId)}`,
  );
  const response = await fetchImpl(url, {
    headers: { authorization: `Bearer ${apiToken}` },
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await parseApiResponse(response);
  if (!payload.result || typeof payload.result !== "object" || Array.isArray(payload.result)) {
    throw new Error("Cloudflare Pages API response does not contain a deployment");
  }
  return payload.result;
}

// Run inside the production concurrency group, immediately before upload. The
// project identifies what is served; a newer tag may never have been deployed.
export async function verifyProductionAdvance({ commitSha, releaseTag, compareCommits, ...api }) {
  const project = await getProject(api);
  if (project.canonical_deployment === null) {
    const deployments = await listDeployments(api);
    if (deployments.some((deployment) => deployment.environment !== "preview")) {
      throw new Error(
        "Production identity unreadable: deployments exist without a canonical commit",
      );
    }
    return `First production deployment: ${releaseTag} (${commitSha})`;
  }
  const deploymentId = project.canonical_deployment?.id;
  if (typeof deploymentId !== "string" || !/^[0-9a-f-]{36}$/i.test(deploymentId)) {
    throw new Error("Production identity unreadable: no canonical deployment ID");
  }
  const deployment = await getDeployment({ ...api, deploymentId });
  const metadata = deployment?.deployment_trigger?.metadata;
  const liveSha = metadata?.commit_hash?.toLowerCase();
  const liveTag =
    (typeof metadata?.commit_message === "string"
      ? metadata.commit_message.match(
          /^release:(site-\d{4}-\d{2}-gw\d{2}-(?:decision|settled|fix\d+))$/,
        )?.[1]
      : null) ?? "live tag unreadable";
  if (!/^[0-9a-f]{40}$/.test(liveSha ?? "")) {
    throw new Error("Production identity unreadable: canonical commit is missing or invalid");
  }
  verifyDeploymentRecord({
    deployment,
    deploymentId,
    project: api.project,
    mode: "production",
    branch: "main",
    commitSha: liveSha,
  });
  const { data: comparison } = await compareCommits({ base: liveSha, head: commitSha });
  const detail = `${releaseTag} (${commitSha}) is ${comparison.status} relative to live ${liveTag} (${liveSha})`;
  if (!["ahead", "identical"].includes(comparison.status)) {
    throw new Error(`Production refused: ${detail}`);
  }
  return `Production accepted: ${detail}`;
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
  const actionEnvironment = requiredEnvironment("ACTION_PAGES_ENVIRONMENT");
  // Preview asserts an alias it demonstrably owns; production asserts that the project's
  // canonical deployment is this one, which is a different question and a different field.
  const previewAlias = mode === "preview" ? requiredEnvironment("EXPECTED_PREVIEW_ALIAS") : null;

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
      verifyDeploymentRecord({ deployment, deploymentId, project, mode, branch, commitSha });

      // The project is read here rather than in the budget step, which runs *before* the
      // upload: its canonical deployment would have been the previous one.
      const served =
        mode === "preview"
          ? verifyPreviewAlias(deployment, previewAlias)
          : verifyCanonicalDeployment(
              await getProject({ accountId, project, apiToken }),
              deploymentId,
            );
      console.log(
        `Verified Cloudflare deployment ${deploymentId}: ${mode} ${branch} ${commitSha} -> ${served}`,
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
