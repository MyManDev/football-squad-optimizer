import { appendFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

export const DAILY_DEPLOYMENT_LIMIT = 10;
export const PREVIEW_DEPLOYMENT_LIMIT = 8;

export function validatedPagesSubdomain(value) {
  const subdomain = String(value ?? "")
    .trim()
    .toLowerCase();
  if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.pages\.dev$/.test(subdomain)) {
    throw new Error("Cloudflare Pages API returned an invalid project subdomain");
  }
  return subdomain;
}

export function validateProjectConfiguration(project) {
  if (project?.production_branch !== "main") {
    throw new Error(
      `Cloudflare Pages project production branch must be main, got ${cleanApiMessage(project?.production_branch)}`,
    );
  }
  if (project?.source != null) {
    throw new Error("Cloudflare Pages project must use Direct Upload, not Git integration");
  }
  return validatedPagesSubdomain(project?.subdomain);
}

// One or more dot-separated hostname labels. Written as a literal rather than assembled
// from a string, because a template literal turns "\." into "." and would quietly accept
// any character where a dot is meant.
const PAGES_DOMAIN_PATTERN =
  /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

// A custom domain attached to the project. Validated the same way as the subdomain rather
// than trusted, because it becomes part of an identity assertion.
export function validatedPagesDomain(value) {
  const domain = String(value ?? "")
    .trim()
    .toLowerCase();
  if (domain.length > 253 || !PAGES_DOMAIN_PATTERN.test(domain)) {
    throw new Error("Cloudflare Pages API returned an invalid project domain");
  }
  return domain;
}

// Every hostname the project may legitimately answer on, as https URLs. Identity
// verification needs the whole set: a production deployment's ``aliases`` array carries the
// attached custom domains, and not the apex ``*.pages.dev`` hostname, so asserting the
// subdomain alone asserts something the API does not report.
export function projectAliasUrls(project) {
  const subdomain = validateProjectConfiguration(project);
  const domains = project?.domains;
  if (domains != null && !Array.isArray(domains)) {
    throw new Error("Cloudflare Pages API returned a non-array project domain list");
  }
  const hostnames = [subdomain, ...(domains ?? []).map((domain) => validatedPagesDomain(domain))];
  return [...new Set(hostnames)].map((hostname) => `https://${hostname}`);
}

export function utcDayBounds(now = new Date()) {
  const start = new Date(now);
  start.setUTCHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 1);
  return { start, end };
}

export function deploymentDecision({ deployments, mode, now = new Date() }) {
  if (!Array.isArray(deployments)) throw new TypeError("deployments must be an array");
  if (!new Set(["preview", "production"]).has(mode)) {
    throw new Error(`Unsupported deployment mode: ${mode}`);
  }

  const { start, end } = utcDayBounds(now);
  const today = deployments.filter((deployment) => {
    const created = new Date(deployment?.created_on ?? Number.NaN);
    return Number.isFinite(created.getTime()) && created >= start && created < end;
  });
  const limit = mode === "preview" ? PREVIEW_DEPLOYMENT_LIMIT : DAILY_DEPLOYMENT_LIMIT;
  return {
    decision: today.length >= limit ? "blocked" : "deploy",
    todayCount: today.length,
  };
}

function cleanApiMessage(value) {
  return String(value ?? "unknown error")
    .replace(/[\r\n]+/g, " ")
    .slice(0, 240);
}

export async function parseApiResponse(response) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Cloudflare Pages API returned non-JSON HTTP ${response.status}`);
  }

  if (!response.ok || payload?.success !== true) {
    const details = Array.isArray(payload?.errors)
      ? payload.errors
          .slice(0, 3)
          .map((error) => `${cleanApiMessage(error?.code)}:${cleanApiMessage(error?.message)}`)
          .join(", ")
      : "unknown error";
    throw new Error(`Cloudflare Pages API returned HTTP ${response.status} (${details})`);
  }
  return payload;
}

export async function getProject({ accountId, project, apiToken, fetchImpl = fetch }) {
  const url = new URL(
    `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/pages/projects/${encodeURIComponent(project)}`,
  );
  const response = await fetchImpl(url, {
    headers: { authorization: `Bearer ${apiToken}` },
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await parseApiResponse(response);
  if (!payload.result || typeof payload.result !== "object" || Array.isArray(payload.result)) {
    throw new Error("Cloudflare Pages API response does not contain a project");
  }
  return payload.result;
}

export async function listDeployments({ accountId, project, apiToken, fetchImpl = fetch }) {
  const deployments = [];
  let page = 1;
  let totalPages = 1;

  do {
    const url = new URL(
      `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/pages/projects/${encodeURIComponent(project)}/deployments`,
    );
    url.searchParams.set("page", String(page));
    url.searchParams.set("per_page", "25");

    const response = await fetchImpl(url, {
      headers: { authorization: `Bearer ${apiToken}` },
      signal: AbortSignal.timeout(15_000),
    });
    const payload = await parseApiResponse(response);
    if (!Array.isArray(payload.result)) {
      throw new Error("Cloudflare Pages API response does not contain a deployment list");
    }
    deployments.push(...payload.result);

    const reportedPages = Number(payload.result_info?.total_pages ?? 1);
    if (!Number.isInteger(reportedPages) || reportedPages < 0 || reportedPages > 1000) {
      throw new Error(`Cloudflare Pages API returned invalid total_pages: ${reportedPages}`);
    }
    totalPages = Math.max(1, reportedPages);
    page += 1;
  } while (page <= totalPages);

  return deployments;
}

function requiredEnvironment(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

async function writeOutput(name, value) {
  const rendered = String(value).replace(/[\r\n]+/g, " ");
  if (process.env.GITHUB_OUTPUT) {
    await appendFile(process.env.GITHUB_OUTPUT, `${name}=${rendered}\n`, "utf8");
  } else {
    console.log(`${name}=${rendered}`);
  }
}

async function main() {
  const apiToken = requiredEnvironment("CLOUDFLARE_API_TOKEN");
  const accountId = requiredEnvironment("CLOUDFLARE_ACCOUNT_ID");
  const project = requiredEnvironment("CLOUDFLARE_PAGES_PROJECT");
  const mode = requiredEnvironment("DEPLOYMENT_MODE");
  if (!/^[0-9a-f]{32}$/i.test(accountId)) throw new Error("Invalid Cloudflare account ID");
  if (!/^[a-z0-9](?:[a-z0-9-]{0,56}[a-z0-9])?$/.test(project)) {
    throw new Error("Invalid Cloudflare Pages project name");
  }
  const projectDetails = await getProject({ accountId, project, apiToken });
  const pagesSubdomain = validateProjectConfiguration(projectDetails);
  const pagesAliases = projectAliasUrls(projectDetails);

  const deployments = await listDeployments({ accountId, project, apiToken });
  const outcome = deploymentDecision({ deployments, mode });
  await writeOutput("decision", outcome.decision);
  await writeOutput("pages_subdomain", pagesSubdomain);
  await writeOutput("pages_aliases", pagesAliases.join(","));
  await writeOutput("today_count", outcome.todayCount);
  await writeOutput(
    "applicable_limit",
    mode === "preview" ? PREVIEW_DEPLOYMENT_LIMIT : DAILY_DEPLOYMENT_LIMIT,
  );
  console.log(
    `Deployment budget: decision=${outcome.decision}, UTC count=${outcome.todayCount}, mode=${mode}`,
  );
}

const entryPoint = process.argv[1] ? resolve(process.argv[1]) : "";
if (entryPoint === fileURLToPath(import.meta.url)) {
  await main();
}
