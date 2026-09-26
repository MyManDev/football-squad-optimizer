/// <reference types="node" />
// @vitest-environment node
/**
 * The web layer rules, read from the source rather than trusted.
 *
 * Every production module under `src` (anything that is not a test, `test/` or
 * `testSupport/`) is parsed with the TypeScript compiler, its relative imports are resolved
 * to files, and three rules are held at zero:
 *
 * 1. The lower zones (`design/`, `lib/`, `i18n/`, `data/`) import nothing from `features/`
 *    or `app/`, not even a type.
 * 2. No runtime validator named in `isValidator` imports a loader other than as a type.
 *    The rule is docs/architecture/member_page_boundaries.md, "Runtime validators import
 *    only the shared errors and types, never the loader that invokes them"; the set it is
 *    held for is the list below, not every module that checks a document.
 * 3. No two production modules import each other's values, directly or around a longer
 *    loop.
 *
 * An edge is a type edge when the build erases it: `import type`, `export type`,
 * `import("x").T`, and an `export { type A } from` whose every name is a type. An
 * `import { type A }` is a value edge, because under this tsconfig's `verbatimModuleSyntax`
 * the build keeps it as `import "x"`. A dynamic `import()` loads later, so it counts for
 * rules 1 and 2 but cannot close a load-time loop in rule 3.
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { posix } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

type Kind = "value" | "type" | "dynamic";

interface Edge {
  from: string;
  line: number;
  to: string;
  kind: Kind;
}

const SRC = fileURLToPath(new URL(".", import.meta.url));

const SOURCES = (readdirSync(SRC, { recursive: true }) as string[])
  .map((name) => name.replace(/\\/g, "/"))
  .filter((name) => /\.tsx?$/.test(name) && !name.endsWith(".d.ts"));

const isProduction = (path: string): boolean =>
  !/\.(test|spec)\.tsx?$/.test(path) && !/(^|\/)(test|testSupport|__tests__)\//.test(path);

const PRODUCTION = SOURCES.filter(isProduction);

/** Relative imports that name a stylesheet, data file or image, not a module to check. */
const ASSET = /\.(css|json|svg|png|jpe?g|webp|gif|woff2?|md|txt)$/;

function specifiers(path: string): { specifier: string; line: number; kind: Kind }[] {
  const source = ts.createSourceFile(
    path,
    readFileSync(`${SRC}${path}`, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: { specifier: string; line: number; kind: Kind }[] = [];
  const add = (node: ts.Node, literal: ts.Node | undefined, kind: Kind): void => {
    if (literal === undefined || !ts.isStringLiteralLike(literal)) return;
    const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
    found.push({ specifier: literal.text, line, kind });
  };
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node)) {
      const typeOnly = node.importClause?.phaseModifier === ts.SyntaxKind.TypeKeyword;
      add(node, node.moduleSpecifier, typeOnly ? "type" : "value");
    } else if (ts.isExportDeclaration(node)) {
      const names = node.exportClause;
      const typeOnly =
        node.isTypeOnly ||
        (names !== undefined &&
          ts.isNamedExports(names) &&
          names.elements.length > 0 &&
          names.elements.every((name) => name.isTypeOnly));
      add(node, node.moduleSpecifier, typeOnly ? "type" : "value");
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      add(node, node.arguments[0], "dynamic");
    } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) {
      add(node, node.argument.literal, "type");
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

const KNOWN = new Set(SOURCES);
const UNRESOLVED: string[] = [];
const EDGES: Edge[] = [];

for (const from of PRODUCTION) {
  for (const { specifier, line, kind } of specifiers(from)) {
    if (!specifier.startsWith(".")) continue;
    const path = specifier.replace(/\?.*$/, "");
    const base = posix.normalize(posix.join(posix.dirname(from), path));
    const to = [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find(
      (candidate) => KNOWN.has(candidate),
    );
    if (to !== undefined) EDGES.push({ from, line, to, kind });
    else if (!ASSET.test(path)) UNRESOLVED.push(`${from}:${line} ${specifier}`);
  }
}

const show = (edge: Edge): string => `${edge.from}:${edge.line} -> ${edge.to} (${edge.kind})`;

const LOWER_ZONES = ["design/", "lib/", "i18n/", "data/"];
const UPPER_ZONES = ["features/", "app/"];

/**
 * Runtime validators this rule names: every `*Shape.ts` check, `adviceResponse.ts`
 * (`checkedAdvice`) and `adviceCapabilities.ts` (`checkedCapabilities`). A validator with
 * another file name is covered only once it is added here. The set this selects, and the
 * loader set below, are pinned file by file in the tests, so a rename cannot drop a module
 * from the rule without a failure.
 */
const NAMED_VALIDATORS = new Set([
  "features/league/advice/adviceResponse.ts",
  "features/league/advice/adviceCapabilities.ts",
]);

const isValidator = (path: string): boolean =>
  /(^|\/)[^/]+Shape\.ts$/.test(path) || NAMED_VALIDATORS.has(path);

/** Loaders fetch the published documents: each feature's `data.ts`, and the site client. */
const isLoader = (path: string): boolean =>
  /^features\/[^/]+\/data\.ts$/.test(path) || path === "data/client.ts";

/** Strongly connected components of more than one module (or a module importing itself). */
function valueCycles(edges: readonly Edge[]): string[][] {
  const next = new Map<string, string[]>();
  for (const { from, to, kind } of edges) {
    if (kind === "value") next.set(from, [...(next.get(from) ?? []), to]);
  }
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const stack: string[] = [];
  const onStack = new Set<string>();
  const cycles: string[][] = [];
  const connect = (node: string): void => {
    index.set(node, index.size);
    low.set(node, index.get(node)!);
    stack.push(node);
    onStack.add(node);
    for (const target of next.get(node) ?? []) {
      if (!index.has(target)) {
        connect(target);
        low.set(node, Math.min(low.get(node)!, low.get(target)!));
      } else if (onStack.has(target)) {
        low.set(node, Math.min(low.get(node)!, index.get(target)!));
      }
    }
    if (low.get(node) !== index.get(node)) return;
    const component: string[] = [];
    let member: string;
    do {
      member = stack.pop()!;
      onStack.delete(member);
      component.push(member);
    } while (member !== node);
    if (component.length > 1 || (next.get(node) ?? []).includes(node)) {
      cycles.push(component.sort());
    }
  };
  for (const node of PRODUCTION) if (!index.has(node)) connect(node);
  return cycles;
}

describe("web architecture", () => {
  it("reads the production modules and resolves every relative import", () => {
    expect(PRODUCTION.length).toBeGreaterThan(100);
    expect(PRODUCTION).toContain("data/client.ts");
    expect(UNRESOLVED).toEqual([]);
  });

  it("finds exactly the validators and loaders the validator rule is held for", () => {
    // Both sets are pinned in full: a validator or loader that is renamed, removed or added
    // fails here, instead of silently changing what the validator rule checks.
    expect(PRODUCTION.filter(isValidator).sort()).toEqual([
      "features/league/advice/adviceCapabilities.ts",
      "features/league/advice/adviceResponse.ts",
      "features/league/advice/adviceShape.ts",
      "features/league/chipShape.ts",
      "features/league/publicationShape.ts",
    ]);
    expect(PRODUCTION.filter(isLoader).sort()).toEqual([
      "data/client.ts",
      "features/fixtures/data.ts",
      "features/league/data.ts",
    ]);
  });

  it("keeps the lower zones free of features and the app shell", () => {
    const upward = EDGES.filter(
      ({ from, to }) =>
        LOWER_ZONES.some((zone) => from.startsWith(zone)) &&
        UPPER_ZONES.some((zone) => to.startsWith(zone)),
    );
    expect(upward.map(show)).toEqual([]);
  });

  it("keeps the named runtime validators from importing a loader", () => {
    const back = EDGES.filter(
      ({ from, to, kind }) => kind !== "type" && isValidator(from) && isLoader(to),
    );
    expect(back.map(show)).toEqual([]);
  });

  it("has no value import cycle between production modules", () => {
    expect(valueCycles(EDGES)).toEqual([]);
  });
});
