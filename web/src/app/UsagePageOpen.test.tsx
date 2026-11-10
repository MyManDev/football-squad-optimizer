import { act, cleanup, render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, it, vi } from "vitest";

import { recordUsage } from "../data/usage";
import { UsagePageOpen } from "./UsagePageOpen";

vi.mock("../data/usage", () => ({ recordUsage: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.mocked(recordUsage).mockClear();
});

it("tells the record once per address and not for a new query string", async () => {
  const router = createMemoryRouter([{ path: "*", element: <UsagePageOpen /> }], {
    initialEntries: ["/fixtures"],
  });
  render(<RouterProvider router={router} />);
  expect(recordUsage).toHaveBeenCalledTimes(1);
  expect(recordUsage).toHaveBeenCalledWith({ step: "open" });
  await act(() => router.navigate("/fixtures?view=team"));
  expect(recordUsage).toHaveBeenCalledTimes(1);
  await act(() => router.navigate("/league/352490"));
  expect(recordUsage).toHaveBeenCalledTimes(2);
});
