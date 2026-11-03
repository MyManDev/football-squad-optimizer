/**
 * A failure is said in the member's language from the service's stable code. A code the
 * member can act on has its own sentence in both languages; any other, known or not, gets
 * the general sentence, and neither the code nor anything the service wrote is ever printed.
 */

import { describe, expect, it } from "vitest";

import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { COMPUTE_COPY, failureSentence } from "./computeCopy";
import {
  ANSWER_MISMATCH,
  ANSWER_OTHER_CAPTURE,
  ANSWER_UNREADABLE,
  PATIENCE_EXHAUSTED,
} from "./useAdviceJob";
import { SERVICE_UNREACHABLE } from "./adviceClient";

/** docs/architecture/backend.md, "Error contract": the advice routes and the job view. */
const SERVICE_CODES = [
  "UNKNOWN_ENTRY",
  "UNKNOWN_STRATEGY",
  "NOT_COMPUTED",
  "NOT_FOUND",
  "IDEMPOTENCY_CONFLICT",
  "REQUEST_CONFLICT",
  "VALIDATION_FAILED",
  "UNSUPPORTED_ADVICE_REQUEST",
  "TOP100_INPUTS_UNAVAILABLE",
  "MANAGERS_WORD_UNAVAILABLE",
  "CHIP_NOT_HELD",
  "PLAN_NOT_FOUND",
  "RATE_LIMITED",
  "OPEN_JOB_LIMITED",
  "DEADLINE_PASSED",
  "NOT_READY",
  "QUEUE_UNAVAILABLE",
  "REQUEST_UNREADABLE",
  "CONTEXT_UNAVAILABLE",
  "ENTRY_NOT_IN_CAPTURE",
  "SWITCH_INPUTS_CHANGED",
];
const PAGE_CODES = [SERVICE_UNREACHABLE, PATIENCE_EXHAUSTED, ANSWER_OTHER_CAPTURE];
/** The same contract's codes and the page's own that give the member nothing to do. */
const GENERAL_CODES = [
  "LEAGUE_NOT_CONNECTED",
  "CHIP_HISTORY_UNKNOWN",
  "QUEUE_INTEGRITY_ERROR",
  "ADVICE_BACKEND_DISABLED",
  "INTERNAL_ERROR",
  "TOO_MANY_ATTEMPTS",
  "DETERMINISM_DEFECT",
  "ADVICE_FAILED",
  ANSWER_UNREADABLE,
  ANSWER_MISMATCH,
];

describe.each(["tr", "en"] as const)("failure sentences in %s", (language) => {
  const copy = COMPUTE_COPY[language];

  it.each([...SERVICE_CODES, ...PAGE_CODES])("%s has a sentence of its own", (code) => {
    const sentence = failureSentence(copy, code);
    expect(sentence).toBe(copy.failures[code]);
    expect(sentence.length).toBeGreaterThan(15);
    expect(sentence).not.toMatch(/[A-Z]{2,}_[A-Z_]+/); // never the raw code
    expect(sentence).not.toMatch(AS_A_CHANCE);
  });

  it.each(GENERAL_CODES)("%s says only that it did not complete", (code) => {
    expect(failureSentence(copy, code)).toBe(copy.failures.unknown);
  });

  it("says only that it did not complete for a code it does not know", () => {
    for (const code of ["SOMETHING_NEW", "", "constructor", "__proto__", null, undefined]) {
      expect(failureSentence(copy, code)).toBe(copy.failures.unknown);
    }
    expect(copy.failures.unknown).not.toContain("SOMETHING_NEW");
  });

  it("names no data capture in a failure", () => {
    for (const sentence of Object.values(copy.failures)) {
      expect(sentence).not.toMatch(/veri kaydı|data capture/i);
    }
  });

  it("names the wait a rate limit asked for, as about, and does without it when hidden", () => {
    expect(failureSentence(copy, "RATE_LIMITED", 60)).toBe(copy.rateLimitedFor(60));
    expect(copy.rateLimitedFor(60)).toMatch(
      language === "tr" ? /Yaklaşık 60 saniye/ : /about 60 seconds/,
    );
    expect(failureSentence(copy, "RATE_LIMITED", null)).toBe(copy.failures.RATE_LIMITED);
    expect(failureSentence(copy, "RATE_LIMITED")).not.toMatch(/\d/);
  });

  it("words every duration as about, without a promise or a measurement caveat", () => {
    expect(copy.duration[3]).toMatch(language === "tr" ? /yaklaşık/ : /about/);
    expect(copy.duration[5]).toMatch(language === "tr" ? /yaklaşık/ : /about/);
    expect(copy.duration[1]).not.toMatch(/\d/);
    for (const text of Object.values(copy.duration)) {
      expect(text).not.toMatch(/ölçülmedi|not measured/i);
    }
    for (const text of [...Object.values(copy.duration), copy.leaveOpen]) {
      expect(text).not.toMatch(/guarantee|always|never more|garanti|kesin|mutlaka/i);
    }
  });
});

it("has the same failure codes in both languages", () => {
  expect(Object.keys(COMPUTE_COPY.tr.failures).sort()).toEqual(
    Object.keys(COMPUTE_COPY.en.failures).sort(),
  );
});
