/** Durable capacity for one browser run; no credentials or player records are stored here. */
import { DEVICE_SOLVE_CEILING_SECONDS } from "./solve/ceiling";

export class DeviceWorkRefused extends Error {
  readonly code: string;
  constructor(code: string) {
    super(code);
    this.code = code;
  }
}
interface Receipt {
  binding: string;
  units: number;
  closed: boolean;
}
const prefix = "llmopt-device-work-v1:";
export function deviceWorkReceipt(id: string): Receipt | undefined {
  let value: unknown;
  try {
    const raw = globalThis.sessionStorage?.getItem(prefix + id);
    if (raw) value = JSON.parse(raw);
  } catch {
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  }
  if (value === undefined) return undefined;
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  const r = value as Partial<Receipt>;
  if (
    typeof r.binding !== "string" ||
    !Number.isInteger(r.units) ||
    r.units! < 0 ||
    r.units! > 84 ||
    typeof r.closed !== "boolean"
  )
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  return r as Receipt;
}
function write(id: string, receipt: Receipt) {
  try {
    globalThis.sessionStorage.setItem(prefix + id, JSON.stringify(receipt));
  } catch {
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  }
}
export function bindDeviceRun(id: string | undefined, binding: string): void {
  if (!id || !/^[0-9a-f]{32}$/.test(id)) throw new DeviceWorkRefused("RUN_ID_REQUIRED");
  const prior = deviceWorkReceipt(id) ?? { binding, units: 0, closed: false };
  if (prior.closed) throw new DeviceWorkRefused("RUN_CANCELLED");
  if (prior.binding !== binding) throw new DeviceWorkRefused("RUN_CONTEXT_CHANGED");
  if (!deviceWorkReceipt(id)) write(id, prior);
}
export function reserveDeviceWork(id: string | undefined, binding: string): void {
  bindDeviceRun(id, binding);
  const prior = deviceWorkReceipt(id!)!;
  const units = Math.ceil(DEVICE_SOLVE_CEILING_SECONDS / 30);
  if (prior.units + units > 84) throw new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED");
  write(id!, { ...prior, units: prior.units + units });
}
export function closeDeviceWork(id: string): boolean {
  const held = deviceWorkReceipt(id);
  if (!held) return false;
  write(id, { ...held, closed: true });
  return true;
}
