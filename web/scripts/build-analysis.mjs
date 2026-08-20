import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const docsRoot = resolve(webRoot, "../docs");
const outputRoot = join(webRoot, "public/analysis");
const indexSource = readFileSync(join(docsRoot, "measurements_index.md"), "utf8");

function cleanCell(value) {
  return value.replaceAll("**", "").replaceAll("`", "").replace(/\s+/g, " ").trim();
}

function parseRows(markdown) {
  const rows = [];
  let phase = "Other";
  for (const line of markdown.split(/\r?\n/)) {
    const heading = line.match(/^##\s+(.+)$/);
    if (heading) {
      phase = cleanCell(heading[1]);
      continue;
    }
    if (!line.startsWith("|") || /^\|\s*-/.test(line) || /\|\s*Artifact\s*\|/.test(line)) {
      continue;
    }
    const cells = line.slice(1, -1).split("|").map(cleanCell);
    if (cells.length >= 2 && cells[0] && cells[1]) {
      rows.push({ artifact: cells[0], finding: cells[1], phase });
    }
  }
  return rows;
}

function matchScore(slug, artifact) {
  const normalized = artifact.toLowerCase();
  if (normalized.includes(slug)) return 10_000 + slug.length;
  const tokens = normalized.match(/[a-z0-9_]{4,}/g) ?? [];
  return Math.max(
    0,
    ...tokens.map((token) => {
      const root = token.replace(/_+$/, "");
      if (root.length < 5) return 0;
      if (slug === root) return 5_000 + root.length;
      if (slug.startsWith(`${root}_`)) return root.length;
      return 0;
    }),
  );
}

function findRow(slug, rows) {
  let best = null;
  let bestScore = 0;
  for (const row of rows) {
    const score = matchScore(slug, row.artifact);
    if (score > bestScore) {
      best = row;
      bestScore = score;
    }
  }
  return best;
}

function titleFrom(markdown, fallback) {
  const title = markdown.match(/^#\s+(.+)$/m)?.[1]?.trim();
  return title ?? fallback.replaceAll("_", " ");
}

function firstSentence(value) {
  return value.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? value;
}

function classify(slug, finding) {
  if (slug.includes("prereg")) return "prereg";
  const text = finding.toLowerCase();
  if (
    [
      "clean negative",
      "honest negative",
      "gate fails",
      "worsens",
      "nothing promoted",
      "not carried forward",
    ].some((signal) => text.includes(signal))
  ) {
    return "negative";
  }
  if (
    ["gate passes", "operational default", "promoted"].some((signal) =>
      text.includes(signal),
    )
  ) {
    return "passed";
  }
  return "descriptive";
}

function artifactDate(jsonPath) {
  if (!jsonPath) return null;
  try {
    const payload = JSON.parse(readFileSync(jsonPath, "utf8"));
    const value = payload.created_utc ?? payload.created_at_utc ?? payload.generated_at_utc;
    return typeof value === "string" && !Number.isNaN(Date.parse(value)) ? value : null;
  } catch {
    return null;
  }
}

const rows = parseRows(indexSource);
const files = readdirSync(docsRoot);
const jsonSlugs = files
  .filter((name) => name.endsWith(".json"))
  .map((name) => basename(name, ".json"))
  .filter((slug) => files.includes(`${slug}.md`));
const preregSlugs = files
  .filter((name) => name.endsWith("_prereg.md"))
  .map((name) => basename(name, ".md"));

const candidates = [
  ...jsonSlugs.map((slug) => ({ slug, hasJson: true })),
  ...preregSlugs.map((slug) => ({ slug, hasJson: false })),
];

rmSync(outputRoot, { force: true, recursive: true });
mkdirSync(outputRoot, { recursive: true });

const entries = [];
for (const candidate of candidates) {
  const row = findRow(candidate.slug.replace(/_prereg$/, ""), rows);
  if (!row) continue;
  const markdownName = `${candidate.slug}.md`;
  const jsonName = candidate.hasJson ? `${candidate.slug}.json` : null;
  const markdown = readFileSync(join(docsRoot, markdownName), "utf8");
  cpSync(join(docsRoot, markdownName), join(outputRoot, markdownName));
  if (jsonName) cpSync(join(docsRoot, jsonName), join(outputRoot, jsonName));
  entries.push({
    slug: candidate.slug,
    title: titleFrom(markdown, candidate.slug),
    date: artifactDate(jsonName ? join(docsRoot, jsonName) : null),
    type: classify(candidate.slug, row.finding),
    phase: row.phase,
    finding: firstSentence(row.finding),
    markdown_path: markdownName,
    json_path: jsonName,
  });
}

entries.sort((left, right) => {
  const byDate = (right.date ?? "").localeCompare(left.date ?? "");
  return byDate || left.title.localeCompare(right.title);
});

if (entries.length < 30) {
  throw new Error(`Expected at least 30 indexed measurement documents, found ${entries.length}.`);
}
if (!entries.some((entry) => entry.type === "negative")) {
  throw new Error("Analysis index must preserve at least one negative result.");
}

writeFileSync(
  join(outputRoot, "index.json"),
  `${JSON.stringify({ contract_version: "web_analysis_index_v1", entries }, null, 2)}\n`,
);
console.log(`Copied ${entries.length} indexed measurement documents to ${outputRoot}.`);
