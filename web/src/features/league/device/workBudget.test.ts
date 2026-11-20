import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bindDeviceRun, closeDeviceWork, deviceWorkReceipt, reserveDeviceWork } from "./workBudget";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());
const id = "b".repeat(32);
describe("durable device run capacity", () => {
  it("binds only when the capacity record survives a read back", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {});
    expect(() => bindDeviceRun(id, "capture")).toThrow("RUN_STORE_UNAVAILABLE");
  });

  it("leaves room in the first write for the entire run", () => {
    bindDeviceRun(id, "capture");
    const key = "llmopt-device-work-v1:" + id;
    const size = sessionStorage.getItem(key)!.length;
    const write = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, k, value) {
      if (value.length > size) throw new DOMException("Full", "QuotaExceededError");
      write.call(this, k, value);
    });
    for (let n = 0; n < 21; n++) reserveDeviceWork(id, "capture");
    expect(deviceWorkReceipt(id)?.units).toBe(84);
  });
  it("retains reservations across reconstructed readers and refuses the next attempt", () => {
    bindDeviceRun(id, "same inputs");
    expect(deviceWorkReceipt(id)?.units).toBe(0);
    for (let attempt = 0; attempt < 21; attempt++) reserveDeviceWork(id, "same inputs");
    expect(deviceWorkReceipt(id)?.units).toBe(84);
    expect(() => reserveDeviceWork(id, "same inputs")).toThrow("RUN_BUDGET_EXHAUSTED");
    expect(deviceWorkReceipt(id)?.units).toBe(84);
  });
  it("keeps a closed run closed and rejects a changed data context", () => {
    reserveDeviceWork(id, "capture one");
    expect(() => reserveDeviceWork(id, "capture two")).toThrow("RUN_CONTEXT_CHANGED");
    expect(closeDeviceWork(id)).toBe(true);
    expect(() => reserveDeviceWork(id, "capture one")).toThrow("RUN_CANCELLED");
    expect(deviceWorkReceipt(id)?.units).toBe(4);
  });
  it("does not initialize over corrupt or unreadable receipts", () => {
    sessionStorage.setItem("llmopt-device-work-v1:" + id, "null");
    expect(() => reserveDeviceWork(id, "capture")).toThrow("RUN_STORE_UNAVAILABLE");
    expect(sessionStorage.getItem("llmopt-device-work-v1:" + id)).toBe("null");
  });
});
