import { afterEach, describe, expect, it, vi } from "vitest";

import { requestsCarrying, watchKeyLeaks } from "./keyLeaks";

const KEY = "sk-test-watch-0001";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.cookie = "planted=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("the key leak watch", () => {
  it("finds the key wherever it was put", () => {
    const watch = watchKeyLeaks(KEY);
    try {
      localStorage.setItem("planted", KEY);
      sessionStorage.setItem("planted", `{"key":"${KEY}"}`);
      document.cookie = `planted=${KEY}`;
      expect(() => indexedDB.open(KEY)).toThrow();
      navigator.sendBeacon("/usage", KEY);
      for (const name of ["log", "info", "warn", "error", "debug", "trace"] as const)
        console[name](new Error(`refused ${KEY}`));
      expect(watch.leaks()).toEqual([
        "Storage.setItem",
        "document.cookie",
        "indexedDB.open",
        "navigator.sendBeacon",
        "console.log",
        "console.info",
        "console.warn",
        "console.error",
        "console.debug",
        "console.trace",
        "stored planted",
        "stored planted",
        "cookie jar",
      ]);
    } finally {
      watch.restore();
    }
  });

  it("finds the key in a request's address, header or body", async () => {
    const fetch = vi.fn(async (_input: string, _init?: RequestInit) => new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    await fetch(`https://site.example/a?key=${KEY}`);
    await fetch("https://site.example/b", { headers: { "x-api-key": KEY } });
    await fetch("https://site.example/d", { method: "POST", body: JSON.stringify({ k: KEY }) });
    await fetch("https://site.example/e", { method: "POST", body: "{}" });
    expect(requestsCarrying(fetch, KEY)).toEqual([
      `https://site.example/a?key=${KEY}`,
      "https://site.example/b",
      "https://site.example/d",
    ]);
  });
});
