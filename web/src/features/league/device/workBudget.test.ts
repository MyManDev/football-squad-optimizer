import { beforeEach, describe, expect, it } from "vitest";
import { bindDeviceRun, closeDeviceWork, deviceWorkReceipt, reserveDeviceWork } from "./workBudget";

beforeEach(() => sessionStorage.clear());
const id = "b".repeat(32);
describe("durable device run capacity", () => {
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
