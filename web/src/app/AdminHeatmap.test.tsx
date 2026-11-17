import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { markUsageAdmin, USAGE_ADMIN_KEY } from "../data/usageAdminFlag";
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

it("offers the mode as soon as the admin page marks the browser, without a reload", async () => {
  const { container } = render(<AdminHeatmap />);
  expect(container).toBeEmptyDOMElement();
  act(() => markUsageAdmin());
  expect(await screen.findByText("heatmap mode")).toBeVisible();
});

it("offers the mode when another tab marks the browser", async () => {
  const { container } = render(<AdminHeatmap />);
  expect(container).toBeEmptyDOMElement();
  localStorage.setItem(USAGE_ADMIN_KEY, "1");
  act(() => {
    window.dispatchEvent(new StorageEvent("storage", { key: USAGE_ADMIN_KEY, newValue: "1" }));
  });
  expect(await screen.findByText("heatmap mode")).toBeVisible();
});

it("stays silent when an unrelated storage key changes", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const { container } = render(<AdminHeatmap />);
  act(() => {
    window.dispatchEvent(new StorageEvent("storage", { key: "something.else", newValue: "1" }));
  });
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(container).toBeEmptyDOMElement();
  expect(fetch).not.toHaveBeenCalled();
});
