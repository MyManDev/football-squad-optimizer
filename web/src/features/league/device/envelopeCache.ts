/** Session storage for one-week advice answers. Run receipts use a different prefix. */
export const DEVICE_ENVELOPE_PREFIX = "llmopt-device-v1:";
const MAX_ENVELOPES = 8;

function generatedAt(storage: Storage, key: string): string {
  try {
    const time = JSON.parse(storage.getItem(key) ?? "null")?.generated_at_utc;
    return typeof time === "string" ? time : "";
  } catch {
    return "";
  }
}

export function retainDeviceEnvelope(address: string, encoded: string): void {
  try {
    const storage = globalThis.sessionStorage;
    const older: string[] = [];
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (key?.startsWith(DEVICE_ENVELOPE_PREFIX) && key !== address) older.push(key);
    }
    // Sort only if a limit calls for eviction. Existing unindexed answers are eligible, too.
    let candidates: string[] | undefined;
    const evictOldest = () => {
      candidates ??= older
        .map((key) => ({ key, time: generatedAt(storage, key) }))
        .sort((a, b) => a.time.localeCompare(b.time) || a.key.localeCompare(b.key))
        .map(({ key }) => key);
      const oldest = candidates.shift();
      if (oldest === undefined) return false;
      storage.removeItem(oldest);
      return true;
    };
    let count = older.length;
    for (;;) {
      try {
        storage.setItem(address, encoded);
        break;
      } catch (error) {
        if (
          !(error instanceof DOMException) ||
          (error.name !== "QuotaExceededError" && error.name !== "NS_ERROR_DOM_QUOTA_REACHED") ||
          !evictOldest()
        )
          return;
        count--;
      }
    }
    while (count >= MAX_ENVELOPES && evictOldest()) count--;
  } catch {
    // The answer already reached the in-memory cache, including when storage is disabled.
  }
}
