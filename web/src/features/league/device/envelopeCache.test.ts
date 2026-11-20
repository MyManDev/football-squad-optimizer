import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DEVICE_ENVELOPE_PREFIX, retainDeviceEnvelope } from "./envelopeCache";

const address = (index: number) => DEVICE_ENVELOPE_PREFIX + index;
const answer = (index: number) =>
  JSON.stringify({ generated_at_utc: new Date(Date.UTC(2026, 0, index + 1)).toISOString() });
beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("keeps the eight newest answers and never evicts sessions or capacity receipts", () => {
  sessionStorage.setItem("llmopt-session", "session");
  sessionStorage.setItem("llmopt-device-work-v1:fixture", "receipt");
  for (const n of [5, 0, 7, 2, 3, 1, 4, 6]) sessionStorage.setItem(address(n), answer(n));
  retainDeviceEnvelope(address(8), answer(8));
  expect(sessionStorage.getItem(address(0))).toBeNull();
  for (let n = 1; n <= 8; n++) expect(sessionStorage.getItem(address(n))).toBe(answer(n));
  expect(sessionStorage.getItem("llmopt-session")).toBe("session");
  expect(sessionStorage.getItem("llmopt-device-work-v1:fixture")).toBe("receipt");
});

it("reclaims only the oldest answer needed for a quota-limited write", () => {
  sessionStorage.setItem(address(1), answer(1));
  sessionStorage.setItem(address(0), answer(0));
  const write = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
    if (this.length >= 2) throw new DOMException("Full", "QuotaExceededError");
    write.call(this, key, value);
  });
  retainDeviceEnvelope(address(2), answer(2));
  expect(sessionStorage.getItem(address(0))).toBeNull();
  expect(sessionStorage.getItem(address(1))).toBe(answer(1));
  expect(sessionStorage.getItem(address(2))).toBe(answer(2));
});

it("preserves existing answers when storage is disabled", () => {
  sessionStorage.setItem(address(0), answer(0));
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("Blocked", "SecurityError");
  });
  retainDeviceEnvelope(address(1), answer(1));
  expect(sessionStorage.getItem(address(0))).toBe(answer(0));
});
