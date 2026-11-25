/// <reference types="node" />
// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  AdviceCapabilitiesError,
  capabilitiesForPage,
  checkedCapabilities,
  llmoptEnabledForWindow,
} from "./adviceCapabilities";

/** The committed contract the service validates its own document against. */
const schema = JSON.parse(
  readFileSync(
    new URL("../../../../../docs/contracts/league_capabilities_v1.schema.json", import.meta.url),
    "utf-8",
  ),
) as {
  required: string[];
  properties: Record<string, { const?: string; required?: string[] }>;
};

const DOCUMENT = {
  contract_version: "league_capabilities_v1",
  league_id: 352490,
  capture_snapshot_id: "fpl-live-gw05",
  season: "2026-27",
  gameweek: 5,
  strategies: {
    "fark-yarat": { windows: [1, 3, 5], requires_rival: true },
    "ortak-koru": { windows: [1], requires_rival: true },
    "saf-puan": { windows: [1, 3, 5], requires_rival: false },
  },
  top100: { available: true, weights: [0, 5, 10, 20, 30, 40, 50] },
  managers_word: { available: true },
};

describe("league capabilities", () => {
  it("requires both release and verified repairs for repair work", () => {
    for (const release of [undefined, false, true])
      for (const repairs of [undefined, false, true])
        expect(
          checkedCapabilities(
            { ...DOCUMENT, llmopt_vnext: release, verified_repairs: repairs },
            352490,
          ).verifiedRepairs,
        ).toBe(release && repairs ? true : undefined);
    expect(() => checkedCapabilities({ ...DOCUMENT, verified_repairs: "true" }, 352490)).toThrow(
      AdviceCapabilitiesError,
    );
  });
  it.each([undefined, false, true])(
    "decodes path and package grants independently under release %s",
    (release) => {
      for (const second of [undefined, false, true]) {
        for (const packages of [undefined, false, true]) {
          for (const paths of [undefined, false, true]) {
            const caps = checkedCapabilities(
              {
                ...DOCUMENT,
                llmopt_vnext: release,
                llmopt_vnext_three_week: second,
                transfer_packages: packages,
                three_week_paths: paths,
              },
              DOCUMENT.league_id,
            );
            expect(caps.transferPackages).toBe(release && packages ? true : undefined);
            expect(caps.threeWeekPaths).toBe(release && second && paths ? true : undefined);
            expect(llmoptEnabledForWindow(caps, 1)).toBe(release === true);
            expect(llmoptEnabledForWindow(caps, 3)).toBe(release === true && second === true);
            expect(llmoptEnabledForWindow(caps, 5)).toBe(false);
            expect(caps.verifiedRepairs).toBeUndefined();
          }
        }
      }
    },
  );
  it("refuses a malformed path grant", () => {
    expect(() =>
      checkedCapabilities({ ...DOCUMENT, three_week_paths: "1" }, DOCUMENT.league_id),
    ).toThrow(AdviceCapabilitiesError);
  });
  it("does not infer three-week permission from a malformed or stale grant", () => {
    const caps = checkedCapabilities(
      { ...DOCUMENT, llmopt_vnext: true, llmopt_vnext_three_week: "true" },
      DOCUMENT.league_id,
    );
    expect(llmoptEnabledForWindow(caps, 3)).toBe(false);
    expect(llmoptEnabledForWindow(null, 3)).toBe(false);
  });
  it.each([undefined, false, true])(
    "advertises grouped preferences only with the release setting %s",
    (enabled) => {
      const caps = checkedCapabilities(
        {
          ...DOCUMENT,
          llmopt_vnext: enabled,
          preference_bundles: { version: "llmopt_preference_bundle_v1" },
        },
        352490,
      );
      expect(caps.llmoptVNext === true).toBe(enabled === true);
      expect(caps.preferenceBundles === true).toBe(enabled === true);
    },
  );
  it.each(["model_opportunity_reservation_v1", "model_opportunity_reservation_v2"])(
    "accepts published chip strategy %s and refuses unknown versions",
    (version) => {
      const chips = {
        held_by_entry: { "101": ["wildcard", "3xc"] },
        strategy: { version, windows: [1, 3, 5] },
      };
      expect(checkedCapabilities({ ...DOCUMENT, chips }, 352490).chipStrategyWindows).toEqual([
        1, 3, 5,
      ]);
      expect(() =>
        checkedCapabilities(
          { ...DOCUMENT, chips: { ...chips, strategy: { ...chips.strategy, version: "unknown" } } },
          352490,
        ),
      ).toThrow(AdviceCapabilitiesError);
    },
  );

  it("distinguishes held chips, no chips and unknown member history", () => {
    const held = { "101": ["wildcard", "3xc"], "202": [] };
    const result = checkedCapabilities({ ...DOCUMENT, chips: { held_by_entry: held } }, 352490);
    expect(result.chipsByEntry).toEqual(held);
    expect(result.chipsByEntry?.["303"]).toBeUndefined();
    expect(checkedCapabilities(DOCUMENT, 352490).chipsByEntry).toBeUndefined();
  });

  it.each([
    null,
    {},
    { held_by_entry: { "0": [] } },
    { held_by_entry: { "101": ["unknown"] } },
    { held_by_entry: { "101": ["wildcard", "wildcard"] } },
  ])("refuses malformed chips %j", (chips) => {
    expect(() => checkedCapabilities({ ...DOCUMENT, chips }, 352490)).toThrow(
      AdviceCapabilitiesError,
    );
  });
  it("reads every field the committed contract requires, under the contract's name", () => {
    expect(schema.properties.contract_version?.const).toBe(DOCUMENT.contract_version);
    expect(Object.keys(DOCUMENT).sort()).toEqual([...schema.required].sort());
    expect(schema.properties.top100?.required).toEqual(["available", "weights"]);
    expect(schema.properties.managers_word?.required).toEqual(["available"]);
  });

  it("hands the page the strategies, their windows and the two switches", () => {
    expect(checkedCapabilities(DOCUMENT, 352490)).toEqual({
      leagueId: 352490,
      captureSnapshotId: "fpl-live-gw05",
      season: "2026-27",
      gameweek: 5,
      strategies: {
        "fark-yarat": { windows: [1, 3, 5], requiresRival: true },
        "ortak-koru": { windows: [1], requiresRival: true },
        "saf-puan": { windows: [1, 3, 5], requiresRival: false },
      },
      top100Weights: [0, 5, 10, 20, 30, 40, 50],
      managersWord: true,
    });
  });

  it("offers only zero when the capture has no Top 100 input, whatever the list says", () => {
    const off = { ...DOCUMENT, top100: { available: false, weights: [0, 20] } };
    expect(checkedCapabilities(off, 352490).top100Weights).toEqual([0]);
    // A setting this page has no radio for is not offered here.
    const odd = { ...DOCUMENT, top100: { available: true, weights: [0, 7, 20, 20] } };
    expect(checkedCapabilities(odd, 352490).top100Weights).toEqual([0, 20]);
  });

  it.each([
    ["not an object", null],
    ["another contract", { ...DOCUMENT, contract_version: "league_state_v1" }],
    ["another league", { ...DOCUMENT, league_id: 1 }],
    ["no capture", { ...DOCUMENT, capture_snapshot_id: "" }],
    ["a gameweek that is not one", { ...DOCUMENT, gameweek: 0 }],
    ["no strategies", { ...DOCUMENT, strategies: [] }],
    [
      "a window that is not 1, 3 or 5",
      { ...DOCUMENT, strategies: { x: { windows: [2], requires_rival: false } } },
    ],
    ["a strategy without its rival rule", { ...DOCUMENT, strategies: { x: { windows: [1] } } }],
    ["a switch that is not a boolean", { ...DOCUMENT, managers_word: { available: "yes" } }],
    ["weights that are not numbers", { ...DOCUMENT, top100: { available: true, weights: ["20"] } }],
  ])("refuses %s", (_name, document) => {
    expect(() => checkedCapabilities(document, 352490)).toThrow(AdviceCapabilitiesError);
  });

  it("speaks about a page only when league, season, gameweek and capture all agree", () => {
    const capabilities = checkedCapabilities(DOCUMENT, 352490);
    const page = { leagueId: 352490, season: "2026-27", gameweek: 5, snapshotId: "fpl-live-gw05" };
    expect(capabilitiesForPage(capabilities, page)).toBe(capabilities);
    // A squad document from before snapshots were named cannot disagree about one.
    expect(capabilitiesForPage(capabilities, { ...page, snapshotId: null })).toBe(capabilities);
    expect(
      capabilitiesForPage(capabilities, { ...page, snapshotId: "fpl-live-gw05-b" }),
    ).toBeNull();
    expect(capabilitiesForPage(capabilities, { ...page, gameweek: 6 })).toBeNull();
    expect(capabilitiesForPage(capabilities, { ...page, season: "2027-28" })).toBeNull();
    expect(capabilitiesForPage(capabilities, { ...page, leagueId: 2 })).toBeNull();
    expect(capabilitiesForPage(null, page)).toBeNull();
  });
});
