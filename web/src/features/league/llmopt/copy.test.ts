/// <reference types="node" />
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { Language } from "../../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { LLMOPT_COPY } from "./copy";

const LANGUAGES: readonly Language[] = ["en", "tr"];

// Keys that held only a caveat or a note about the method. None may come back.
const REMOVED = [
  "notProven",
  "priceUnproven",
  "comparisonScope",
  "scenarioHypothetical",
  "bankWitness",
] as const;

function strings(node: unknown, path: string, into: Map<string, string>) {
  if (typeof node === "string") into.set(path, node);
  else if (typeof node === "function") {
    const call = node as (...args: unknown[]) => unknown;
    into.set(path, String(call(...Array.from({ length: Math.max(call.length, 1) }, () => 1))));
  } else if (node && typeof node === "object")
    for (const [key, value] of Object.entries(node)) strings(value, `${path}.${key}`, into);
}

const page = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "LLMOptPage.tsx"), "utf8");

describe("the LLMOPT copy", () => {
  it.each(LANGUAGES)("carries none of the removed caveat keys in %s", (language) => {
    const copy = LLMOPT_COPY[language] as Record<string, unknown>;
    for (const key of REMOVED) expect(Object.keys(copy)).not.toContain(key);
  });

  it.each(LANGUAGES)("carries no caveat or chance wording in %s", (language) => {
    const texts = new Map<string, string>();
    strings(LLMOPT_COPY[language], language, texts);
    expect(texts.size).toBeGreaterThan(100);
    const offenders = [...texts]
      .filter(([, text]) => AS_A_CAVEAT.test(text) || AS_A_CHANCE.test(text))
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
  });

  it("gives the heading and the chat speaker from the copy in both languages", () => {
    for (const language of LANGUAGES) {
      expect(LLMOPT_COPY[language].title).toBe("LLMOPT");
      expect(LLMOPT_COPY[language].assistant).toBe("LLMOPT");
    }
    expect(page).not.toMatch(/"LLMOPT"|>LLMOPT</);
    expect(page).toContain("{copy.title}");
    expect(page).toContain("copy.assistant");
  });

  it("keeps the same keys in both languages", () => {
    const keys = (language: Language) => {
      const texts = new Map<string, string>();
      strings(LLMOPT_COPY[language], "", texts);
      return [...texts.keys()].sort();
    };
    expect(keys("tr")).toEqual(keys("en"));
  });
});
