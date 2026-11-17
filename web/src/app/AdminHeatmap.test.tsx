import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { USAGE_ADMIN_KEY } from "../data/usageAdminFlag";
import { AdminHeatmap } from "./AdminHeatmap";

const loaded = vi.hoisted(() => vi.fn());

vi.mock("../features/usageAdmin/HeatmapMode", () => {
  loaded();
  return { HeatmapMode: () => <p>heatmap mode</p> };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.removeItem(USAGE_ADMIN_KEY);
});

it("loads nothing, asks nothing and draws nothing for a visitor who is not an admin", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<AdminHeatmap />);
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(container).toBeEmptyDOMElement();
  expect(loaded).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("loads the mode for a browser marked as an admin's", async () => {
  localStorage.setItem(USAGE_ADMIN_KEY, "1");
  render(<AdminHeatmap />);
  expect(await screen.findByText("heatmap mode")).toBeVisible();
  expect(loaded).toHaveBeenCalledTimes(1);
});
