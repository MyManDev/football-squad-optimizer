import { vi, type Mock } from "vitest";

/**
 * Watches every place a member's model key must never reach (ADR 0017): the browser's
 * storage, IndexedDB, cookies, beacons, the console and the address. `leaks()` names each
 * place that received the key; `requestsCarrying` names each request that carried it.
 */
export function watchKeyLeaks(key: string) {
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  const cookie = vi.spyOn(Document.prototype, "cookie", "set");
  const openDatabase = vi.fn(() => {
    throw new Error("IndexedDB is not available in this test.");
  });
  vi.stubGlobal("indexedDB", { open: openDatabase, deleteDatabase: vi.fn() });
  const beacon = vi.fn(() => true);
  Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
  const consoles = (["log", "info", "warn", "error", "debug", "trace"] as const).map(
    (name) => [name, vi.spyOn(console, name).mockImplementation(() => {})] as const,
  );
  const carries = (args: readonly unknown[]) => args.some((value) => text(value).includes(key));
  return {
    leaks(): string[] {
      const found: string[] = [];
      if (setItem.mock.calls.some(carries)) found.push("Storage.setItem");
      if (cookie.mock.calls.some(carries)) found.push("document.cookie");
      if (openDatabase.mock.calls.length > 0) found.push("indexedDB.open");
      if (beacon.mock.calls.some(carries)) found.push("navigator.sendBeacon");
      for (const [name, spy] of consoles)
        if (spy.mock.calls.some(carries)) found.push(`console.${name}`);
      for (const storage of [localStorage, sessionStorage])
        for (let index = 0; index < storage.length; index++) {
          const name = storage.key(index) ?? "";
          if (`${name}${storage.getItem(name)}`.includes(key)) found.push(`stored ${name}`);
        }
      if (document.cookie.includes(key)) found.push("cookie jar");
      if (window.location.href.includes(key)) found.push("address");
      return found;
    },
    restore() {
      Reflect.deleteProperty(navigator, "sendBeacon");
    },
  };
}

/** The text of one logged or stored value, an error's message and stack included. */
function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return `${value.name} ${value.message} ${value.stack ?? ""}`;
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** One request a fetch mock received: its address, every header and its body as text. */
export function sentRequests(fetch: Mock) {
  return fetch.mock.calls.map(([input, init]: unknown[]) => {
    const request = input instanceof Request ? input : null;
    const options = (init ?? {}) as RequestInit;
    const url = request ? request.url : String(input);
    const headers = [...new Headers(options.headers ?? request?.headers).entries()];
    const body = typeof options.body === "string" ? options.body : "";
    return { url, headers, body };
  });
}

/** The addresses of the requests whose address, headers or body carried the key. */
export function requestsCarrying(fetch: Mock, key: string): string[] {
  return sentRequests(fetch)
    .filter(({ url, headers, body }) =>
      [url, body, ...headers.flat()].some((part) => part.includes(key)),
    )
    .map(({ url }) => url);
}
