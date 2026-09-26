/// <reference types="node" />
// @vitest-environment node
/**
 * No two features depend on each other, directly or around a longer loop.
 *
 * A feature is a directory under `src/features/`. Every production module (anything that is
 * not a test, `test/` or `testSupport/`) is parsed with the TypeScript compiler and each
 * relative import is resolved to a file. An import from one feature into another is a
 * feature edge whatever its kind: a type-only import, a value import and a lazy `import()`
 * all say the importing feature needs the other one, so all three count here, unlike a
 * module-level load cycle where an erased type edge cannot close a loop.
 *
 * One-way composition is allowed (the league pages show the fixtures feature's list, the
 * moves page reads the league's published members). A loop is not: vocabulary two features
 * share belongs in a lower zone, as the play modes and planning windows do in
 * `lib/decisionVocabulary.ts`.
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { posix } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = fileURLToPath(new URL(".", import.meta.url));

const SOURCES = (readdirSync(SRC, { recursive: true }) as string[])
  .map((name) => name.replace(/\\/g, "/"))
  .filter((name) => /\.tsx?$/.test(name) && !name.endsWith(".d.ts"));

const isProduction = (path: string): boolean =>
  !/\.(test|spec)\.tsx?$/.test(path) && !/(^|\/)(test|testSupport|__tests__)\//.test(path);

const PRODUCTION = SOURCES.filter(isProduction);
const KNOWN = new Set(SOURCES);

/** Every module specifier a file names: imports, re-exports, `import()` and `import("x").T`. */
function specifiers(path: string): { specifier: string; line: number }[] {
  const source = ts.createSourceFile(
    path,
    readFileSync(`${SRC}${path}`, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: { specifier: string; line: number }[] = [];
  const add = (node: ts.Node, literal: ts.Node | undefined): void => {
    if (literal === undefined || !ts.isStringLiteralLike(literal)) return;
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    found.push({ specifier: literal.text, line });
  };
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      add(node, node.moduleSpecifier);
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      add(node, node.arguments[0]);
    } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) {
      add(node, node.argument.literal);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

const featureOf = (path: string): string | undefined => /^features\/([^/]+)\//.exec(path)?.[1];

interface FeatureEdge {
  from: string;
  to: string;
  at: string;
}

const EDGES: FeatureEdge[] = [];
const UNRESOLVED: string[] = [];

for (const file of PRODUCTION) {
  const from = featureOf(file);
  if (from === undefined) continue;
  for (const { specifier, line } of specifiers(file)) {
    if (!specifier.startsWith(".")) continue;
    const path = specifier.replace(/\?.*$/, "");
    const base = posix.normalize(posix.join(posix.dirname(file), path));
    const target = [
      base,
      `${base}.ts`,
      `${base}.tsx`,
      `${base}/index.ts`,
      `${base}/index.tsx`,
    ].find((candidate) => KNOWN.has(candidate));
    if (target === undefined) {
      if (!/\.(css|json|svg|png|jpe?g|webp|gif|woff2?|md|txt)$/.test(path)) {
        UNRESOLVED.push(`${file}:${line} ${specifier}`);
      }
      continue;
    }
    const to = featureOf(target);
    if (to !== undefined && to !== from) EDGES.push({ from, to, at: `${file}:${line}` });
  }
}

/** Groups of features that reach each other (strongly connected, more than one feature). */
function featureCycles(edges: readonly FeatureEdge[]): string[][] {
  const next = new Map<string, Set<string>>();
  for (const { from, to } of edges) next.set(from, (next.get(from) ?? new Set()).add(to));
  const nodes = [...new Set(edges.flatMap(({ from, to }) => [from, to]))].sort();
  const reach = (start: string): Set<string> => {
    const seen = new Set<string>();
    const queue = [start];
    while (queue.length > 0) {
      for (const target of next.get(queue.pop()!) ?? []) {
        if (!seen.has(target)) {
          seen.add(target);
          queue.push(target);
        }
      }
    }
    return seen;
  };
  const reaches = new Map(nodes.map((node) => [node, reach(node)]));
  const cycles: string[][] = [];
  const placed = new Set<string>();
  for (const node of nodes) {
    if (placed.has(node) || !reaches.get(node)!.has(node)) continue;
    const group = nodes.filter(
      (other) => reaches.get(node)!.has(other) && reaches.get(other)!.has(node),
    );
    for (const member of group) placed.add(member);
    cycles.push(group);
  }
  return cycles;
}

describe("web feature boundaries", () => {
  it("reads the feature modules and resolves every relative import", () => {
    expect(PRODUCTION.filter((path) => featureOf(path) !== undefined).length).toBeGreaterThan(50);
    expect(UNRESOLVED).toEqual([]);
    // The reader sees the one-way compositions that exist today, so an empty cycle list
    // below is a finding and not a reader that found no edges at all.
    const pairs = new Set(EDGES.map(({ from, to }) => `${from} -> ${to}`));
    expect(pairs).toContain("moves -> league");
  });

  it("has no import cycle between features", () => {
    const cycles = featureCycles(EDGES);
    const inside = (group: string[]): string[] =>
      EDGES.filter(({ from, to }) => group.includes(from) && group.includes(to)).map(
        ({ from, to, at }) => `${at} (${from} -> ${to})`,
      );
    expect(cycles.map((group) => ({ features: group, edges: inside(group) }))).toEqual([]);
  });

  it("keeps the league feature free of the moves page", () => {
    const edges = EDGES.filter(({ from, to }) => from === "league" && to === "moves");
    expect(edges.map(({ at }) => at)).toEqual([]);
  });
});
