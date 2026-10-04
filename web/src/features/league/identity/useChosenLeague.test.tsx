/** The league the visitor opened: remembered in the browser, shared across its tabs. */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readChosenLeague, useChosenLeague, writeChosenLeague } from "./useChosenLeague";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
beforeEach(() => {
  localStorage.clear();
  writeChosenLeague(null);
});

function Probe() {
  const { leagueId } = useChosenLeague();
  return <output>{leagueId === null ? "none" : String(leagueId)}</output>;
}

describe("the chosen league", () => {
  it("remembers a positive whole number and forgets anything else", () => {
    render(<Probe />);
    expect(screen.getByRole("status")).toHaveTextContent("none");
    act(() => writeChosenLeague(352490));
    expect(screen.getByRole("status")).toHaveTextContent("352490");
    expect(localStorage.getItem("squadopt.league")).toBe("352490");
    act(() => writeChosenLeague(-3));
    expect(readChosenLeague()).toBeNull();
    expect(localStorage.getItem("squadopt.league")).toBeNull();
  });

  it("follows another tab through the storage event", () => {
    render(<Probe />);
    act(() => {
      localStorage.setItem("squadopt.league", "352490");
      window.dispatchEvent(new StorageEvent("storage", { key: "squadopt.league" }));
    });
    expect(screen.getByRole("status")).toHaveTextContent("352490");
    act(() => {
      localStorage.removeItem("squadopt.league");
      // A cleared store fires with a null key.
      window.dispatchEvent(new StorageEvent("storage", { key: null }));
    });
    expect(screen.getByRole("status")).toHaveTextContent("none");
    act(() => {
      localStorage.setItem("squadopt.league", "352490");
      window.dispatchEvent(new StorageEvent("storage", { key: "squadopt.language" }));
    });
    // Another key's change is not this store's business.
    expect(screen.getByRole("status")).toHaveTextContent("none");
  });

  it("keeps the choice for the visit when storage refuses it", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<Probe />);
    act(() => writeChosenLeague(352490));
    expect(screen.getByRole("status")).toHaveTextContent("352490");
  });
});
