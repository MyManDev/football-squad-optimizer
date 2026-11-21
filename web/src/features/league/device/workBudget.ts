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
  repairCandidates?: string[];
  repairSelection?: string;
}
const digest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const workerUnits = Math.ceil(DEVICE_SOLVE_CEILING_SECONDS / 30);
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
    typeof r.closed !== "boolean" ||
    (r.repairCandidates !== undefined &&
      (!Array.isArray(r.repairCandidates) ||
        r.repairCandidates.length > 2 ||
        !r.repairCandidates.every(digest) ||
        new Set(r.repairCandidates).size !== r.repairCandidates.length)) ||
    (r.repairSelection !== undefined &&
      (!digest(r.repairSelection) || !r.repairCandidates?.includes(r.repairSelection)))
  )
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  return r as Receipt;
}
function write(id: string, receipt: Receipt) {
  try {
    // Reserve the full shape when the run is bound, including its two repair candidates
    // and selected replay, so a full tab can still update an existing reservation.
    const digestSpace = "0".repeat(64);
    const capacity = JSON.stringify({
      ...receipt,
      units: 84,
      closed: false,
      repairCandidates: [digestSpace, digestSpace],
      repairSelection: digestSpace,
    }).length;
    const value = JSON.stringify(receipt).padEnd(capacity);
    const key = prefix + id;
    globalThis.sessionStorage.setItem(key, value);
    if (globalThis.sessionStorage.getItem(key) !== value) throw new Error("Receipt not retained");
  } catch {
    throw new DeviceWorkRefused("RUN_STORE_UNAVAILABLE");
  }
}
export function bindDeviceRun(id: string | undefined, binding: string): void {
  if (!id || !/^[0-9a-f]{32}$/.test(id)) throw new DeviceWorkRefused("RUN_ID_REQUIRED");
  const prior = deviceWorkReceipt(id);
  if (!prior) {
    write(id, { binding, units: 0, closed: false });
    return;
  }
  if (prior.closed) throw new DeviceWorkRefused("RUN_CANCELLED");
  if (prior.binding !== binding) throw new DeviceWorkRefused("RUN_CONTEXT_CHANGED");
}
export function reserveDeviceWork(id: string | undefined, binding: string): void {
  bindDeviceRun(id, binding);
  const prior = deviceWorkReceipt(id!)!;
  const heldForSelection =
    prior.repairCandidates?.length && !prior.repairSelection ? workerUnits : 0;
  if (prior.units + workerUnits + heldForSelection > 84)
    throw new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED");
  write(id!, { ...prior, units: prior.units + workerUnits });
}

/** Persist an attempt before starting its worker, retaining capacity for one selected replay. */
export function claimDeviceRepair(
  id: string,
  binding: string,
  addressDigest: string,
  verify: boolean,
  cacheHit: boolean,
  existing?: "recover",
): boolean {
  bindDeviceRun(id, binding);
  const prior = deviceWorkReceipt(id)!;
  const candidates = prior.repairCandidates ?? [];
  const repeated = verify
    ? prior.repairSelection === addressDigest
    : candidates.includes(addressDigest);
  if (repeated && existing !== "recover") return false;
  if (verify) {
    if ((prior.repairSelection && !repeated) || !candidates.includes(addressDigest))
      throw new DeviceWorkRefused("RUN_BASE_REQUIRED");
  } else {
    if (
      (prior.repairSelection && prior.repairSelection !== addressDigest) ||
      (!repeated && candidates.length >= 2)
    )
      throw new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED");
  }
  const units = prior.units + (!verify && cacheHit ? 0 : workerUnits);
  if (units + (verify ? 0 : workerUnits) > 84) throw new DeviceWorkRefused("RUN_BUDGET_EXHAUSTED");
  write(id, {
    ...prior,
    units,
    ...(verify
      ? { repairSelection: addressDigest }
      : { repairCandidates: repeated ? candidates : [...candidates, addressDigest] }),
  });
  return true;
}
export function closeDeviceWork(id: string): boolean {
  const held = deviceWorkReceipt(id);
  if (!held) return false;
  write(id, { ...held, closed: true });
  return true;
}
