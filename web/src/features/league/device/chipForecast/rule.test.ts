import { describe, expect, it } from "vitest";

import fixture from "../../../../fixtures/chip-forecast/cases.json";
import {
  CHIP_NAMES,
  ChipForecastError,
  chipForecast,
  holdingThreshold,
  MEASURED_RESERVATION,
  MEASURED_THRESHOLD_POLICY,
  PROTOCOL_HOLDING_VALUES,
  scaledExpectedPoints,
  type ChipForecastInputs,
} from "./rule";

it("pins the measured rule and the game's chip order to Python", () => {
  expect(CHIP_NAMES).toEqual(fixture.constants.chip_names);
  expect(PROTOCOL_HOLDING_VALUES).toEqual(fixture.constants.holding_values);
  expect(MEASURED_THRESHOLD_POLICY).toBe(fixture.constants.threshold_policy);
  expect(MEASURED_RESERVATION).toBe(fixture.constants.reserve);
});

describe("the pure Python rule parity", () => {
  for (const row of fixture.cases) {
    it(row.name, () => {
      const inputs = structuredClone(row.inputs) as ChipForecastInputs;
      const before = structuredClone(inputs);
      expect(chipForecast(inputs)).toEqual(row.reference);
      expect(inputs).toEqual(before);
    });
  }
  for (const row of fixture.refusals) {
    it(`refuses ${row.name}`, () => {
      expect(() => chipForecast(row.inputs as unknown as ChipForecastInputs)).toThrow(
        ChipForecastError,
      );
    });
  }
});

it("keeps the threshold boundary strict and scales blank and double weeks", () => {
  expect(holdingThreshold("fixed", 20, 1, 19, 19)).toBe(20);
  expect(holdingThreshold("decaying", 20, 6, 6, 6)).toBe(0);
  expect(() => holdingThreshold("fixed", 20, 1, 19, 20)).toThrow(ChipForecastError);
  expect(scaledExpectedPoints(8, 0, 2)).toBeNull();
  expect(scaledExpectedPoints(8, 1, 0)).toBe(0);
  expect(scaledExpectedPoints(8, 1, 2)).toBe(16);
  expect(scaledExpectedPoints(-8, 1, 2)).toBe(0);
});

it.each([NaN, Infinity, -Infinity])("refuses nonfinite input %s", (value) => {
  const inputs = structuredClone(fixture.cases[0]!.inputs) as ChipForecastInputs;
  inputs.squad[0]!.expected_points = value;
  expect(() => chipForecast(inputs)).toThrow(ChipForecastError);
});
