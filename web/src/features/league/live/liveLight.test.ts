/**
 * The heading's light: it follows the board drawn, and breathes once for each newer read, never
 * again for the same read when the follow window closes and opens on it.
 */

import { describe, expect, it } from "vitest";

import { createLiveLight } from "./liveLight";

describe("the heading's light", () => {
  it("breathes for a newer read while a match is played", () => {
    const light = createLiveLight();
    light.set({ entryId: 1, playing: true, breath: "read-1" });
    expect(light.get()).toEqual({ entryId: 1, playing: true, breath: "read-1" });
    light.set({ entryId: 1, playing: true, breath: "read-2" });
    expect(light.get()?.breath).toBe("read-2");
  });

  it("stands still when it comes on again for a read it has breathed for", () => {
    const light = createLiveLight();
    light.set({ entryId: 1, playing: true, breath: "read-1" });
    // The follow window closes, then opens again at the next kickoff on the same board.
    light.set({ entryId: 1, playing: false, breath: "read-1" });
    light.set({ entryId: 1, playing: true, breath: "read-1" });
    expect(light.get()).toEqual({ entryId: 1, playing: true, breath: null });
  });

  it("tells its readers only of a change", () => {
    const light = createLiveLight();
    let told = 0;
    light.subscribe(() => {
      told += 1;
    });
    light.set({ entryId: 1, playing: true, breath: "read-1" });
    light.set({ entryId: 1, playing: true, breath: "read-1" });
    expect(told).toBe(1);
  });
});
