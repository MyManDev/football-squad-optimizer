import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  OWN_KEY_IDLE_MS,
  clearOwnKey,
  heldModel,
  localBaseUrl,
  setOwnKey,
  useOwnKey,
  withOwnKey,
  type ProviderCredential,
} from "./ownKey";

const KEY = "sk-test-holder-0001";

afterEach(() => {
  clearOwnKey();
  vi.useRealTimers();
});

function heldCredential(): Promise<ProviderCredential> {
  return withOwnKey(async (credential) => credential);
}

describe("the own key holder", () => {
  it("holds the key for a call and shows only the provider and the model", async () => {
    expect(setOwnKey({ provider: "openai", model: " gpt-5-mini ", key: ` ${KEY} ` })).toBe(true);
    expect(heldModel()).toEqual({ provider: "openai", model: "gpt-5-mini" });
    expect(JSON.stringify(heldModel())).not.toContain(KEY);
    await expect(heldCredential()).resolves.toEqual({
      provider: "openai",
      model: "gpt-5-mini",
      key: KEY,
    });
  });

  it("deletes the key at once on clear", async () => {
    setOwnKey({ provider: "anthropic", model: "claude-sonnet-4-5", key: KEY });
    clearOwnKey();
    expect(heldModel()).toBeNull();
    await expect(heldCredential()).rejects.toThrow("No model key is held.");
  });

  it("refuses an input it cannot use, and keeps what it held", () => {
    setOwnKey({ provider: "groq", model: "openai/gpt-oss-20b", key: KEY });
    for (const input of [
      { provider: "azure", model: "m", key: KEY },
      { provider: "openai", model: "  ", key: KEY },
      { provider: "openai", model: "two words", key: KEY },
      { provider: "openai", model: "m", key: "" },
      { provider: "openai", model: "m", key: "has a space" },
      { provider: "openai", model: "m", key: "x".repeat(1025) },
      { provider: "local", model: "llama3.1", key: "" },
      { provider: "local", model: "llama3.1", key: "", baseUrl: "https://example.com/v1" },
    ])
      expect(setOwnKey(input)).toBe(false);
    expect(heldModel()).toEqual({ provider: "groq", model: "openai/gpt-oss-20b" });
  });

  it("takes a local server on a loopback address, with or without a key", async () => {
    expect(
      setOwnKey({
        provider: "local",
        model: "llama3.1",
        key: "",
        baseUrl: "http://localhost:11434/v1/",
      }),
    ).toBe(true);
    await expect(heldCredential()).resolves.toEqual({
      provider: "local",
      model: "llama3.1",
      key: "",
      baseUrl: "http://localhost:11434/v1",
    });
  });

  it.each([
    ["http://localhost:11434/v1", "http://localhost:11434/v1"],
    ["http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/v1"],
    ["http://localhost:8080", "http://localhost:8080"],
    ["https://localhost:11434/v1", null],
    ["http://localhost/v1", null],
    ["http://localhost:80/v1", null],
    ["http://example.com:11434/v1", null],
    ["http://127.0.0.2:11434/v1", null],
    ["http://user:pass@localhost:11434/v1", null],
    ["http://localhost:11434/v1?next=x", null],
    ["http://localhost:11434/v1#x", null],
    ["localhost:11434", null],
    ["", null],
  ])("reads %s as a local base of %s", (text, base) => {
    expect(localBaseUrl(text)).toBe(base);
  });

  it("deletes the key after 30 minutes without a request", () => {
    vi.useFakeTimers();
    setOwnKey({ provider: "mistral", model: "mistral-small-latest", key: KEY });
    vi.advanceTimersByTime(OWN_KEY_IDLE_MS - 1);
    expect(heldModel()).not.toBeNull();
    vi.advanceTimersByTime(1);
    expect(heldModel()).toBeNull();
  });

  it("counts each request as activity for the idle timer", async () => {
    vi.useFakeTimers();
    setOwnKey({ provider: "deepseek", model: "deepseek-chat", key: KEY });
    vi.advanceTimersByTime(OWN_KEY_IDLE_MS - 1000);
    await heldCredential();
    vi.advanceTimersByTime(OWN_KEY_IDLE_MS - 1000);
    expect(heldModel()).not.toBeNull();
    vi.advanceTimersByTime(1000);
    expect(heldModel()).toBeNull();
  });

  it("deletes a key whose 30 minutes passed while the tab was asleep", async () => {
    // A sleeping laptop stops timers, not the clock.
    vi.useFakeTimers({ toFake: ["Date"] });
    setOwnKey({ provider: "groq", model: "openai/gpt-oss-20b", key: KEY });
    vi.setSystemTime(Date.now() + OWN_KEY_IDLE_MS);
    await expect(heldCredential()).rejects.toThrow("No model key is held.");
    expect(heldModel()).toBeNull();

    setOwnKey({ provider: "groq", model: "openai/gpt-oss-20b", key: KEY });
    vi.setSystemTime(Date.now() + OWN_KEY_IDLE_MS);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(heldModel()).toBeNull();
  });

  it("deletes the key when the page is left", () => {
    setOwnKey({ provider: "openrouter", model: "openai/gpt-5-mini", key: KEY });
    window.dispatchEvent(new Event("pagehide"));
    expect(heldModel()).toBeNull();
  });

  it("tells a component when the key is set and deleted", () => {
    const { result } = renderHook(() => useOwnKey());
    expect(result.current).toBeNull();
    act(() => void setOwnKey({ provider: "gemini", model: "gemini-2.5-flash", key: KEY }));
    expect(result.current).toEqual({ provider: "gemini", model: "gemini-2.5-flash" });
    act(() => clearOwnKey());
    expect(result.current).toBeNull();
  });
});
