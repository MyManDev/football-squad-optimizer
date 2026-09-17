/**
 * A failure is said in the member's language from the service's stable code. Every code
 * the service documents has its own sentence in both languages, an unknown one gets the
 * general sentence, and neither the code nor anything the service wrote is ever printed.
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
  "LEAGUE_NOT_CONNECTED",
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
  "RATE_LIMITED",
  "NOT_READY",
  "QUEUE_UNAVAILABLE",
  "QUEUE_INTEGRITY_ERROR",
  "ADVICE_BACKEND_DISABLED",
  "INTERNAL_ERROR",
  "TOO_MANY_ATTEMPTS",
  "REQUEST_UNREADABLE",
  "CONTEXT_UNAVAILABLE",
  "ENTRY_NOT_IN_CAPTURE",
  "SWITCH_INPUTS_CHANGED",
  "DETERMINISM_DEFECT",
  "ADVICE_FAILED",
];
const PAGE_CODES = [
  SERVICE_UNREACHABLE,
  PATIENCE_EXHAUSTED,
  ANSWER_UNREADABLE,
  ANSWER_MISMATCH,
  ANSWER_OTHER_CAPTURE,
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

  it("says only that it did not complete for a code it does not know", () => {
    for (const code of ["SOMETHING_NEW", "", "constructor", "__proto__", null, undefined]) {
      expect(failureSentence(copy, code)).toBe(copy.failures.unknown);
    }
    expect(copy.failures.unknown).not.toContain("SOMETHING_NEW");
  });

  it("names the wait a rate limit asked for, as about, and does without it when hidden", () => {
    expect(failureSentence(copy, "RATE_LIMITED", 60)).toBe(copy.rateLimitedFor(60));
    expect(copy.rateLimitedFor(60)).toMatch(
      language === "tr" ? /Yaklaşık 60 saniye/ : /about 60 seconds/,
    );
    expect(failureSentence(copy, "RATE_LIMITED", null)).toBe(copy.failures.RATE_LIMITED);
    expect(failureSentence(copy, "RATE_LIMITED")).not.toMatch(/\d/);
  });

  it("words every duration as about, and none as a promise", () => {
    expect(copy.duration[3]).toMatch(language === "tr" ? /yaklaşık/ : /about/);
    expect(copy.duration[5]).toMatch(language === "tr" ? /yaklaşık/ : /about/);
    expect(copy.duration[1]).not.toMatch(/\d/);
    expect(copy.durationNote).toMatch(language === "tr" ? /söz değildir/ : /not a promise/);
    for (const text of [...Object.values(copy.duration), copy.durationNote, copy.leaveOpen]) {
      expect(text).not.toMatch(/guarantee|always|never more|garanti|kesin|mutlaka/i);
    }
  });
});

it("has the same failure codes in both languages", () => {
  expect(Object.keys(COMPUTE_COPY.tr.failures).sort()).toEqual(
    Object.keys(COMPUTE_COPY.en.failures).sort(),
  );
});
