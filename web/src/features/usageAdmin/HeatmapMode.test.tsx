import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { usageReportFixture } from "../../testSupport/usageReport";
import { forgetHeatmapReads } from "./heatmap";
import { HeatmapMode } from "./HeatmapMode";

const MEMBER = "/league/352490/members/35249001";

function serve(me: () => Response, report: () => unknown = usageReportFixture) {
  const fetch = vi.fn(async (url: string) =>
    url.endsWith("/report/me") ? me() : Response.json(report()),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const yes = () => Response.json({ contract_version: "usage_admin_v1", admin: true });
const asked = (fetch: ReturnType<typeof serve>, path: string) =>
  fetch.mock.calls.filter(([url]) => url.split("?")[0] === path).length;

function mount(at = MEMBER) {
  const router = createMemoryRouter([{ path: "*", element: <HeatmapMode /> }], {
    initialEntries: [at],
  });
  render(
    <LanguageProvider initialLanguage="en">
      <RouterProvider router={router} />
    </LanguageProvider>,
  );
  return router;
}

/** A zone on the page, at a box of its own. */
function zone(word: string, box: { left: number; top: number; width: number; height: number }) {
  const element = document.createElement("section");
  element.setAttribute("data-zone", word);
  element.getBoundingClientRect = () =>
    ({
      ...box,
      right: box.left + box.width,
      bottom: box.top + box.height,
      x: box.left,
      y: box.top,
      toJSON: () => ({}),
    }) as DOMRect;
  document.body.append(element);
  return element;
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("coarse") }));
  vi.spyOn(window.screen, "width", "get").mockReturnValue(390);
  vi.spyOn(window.screen, "height", "get").mockReturnValue(844);
  vi.stubGlobal("requestAnimationFrame", (draw: FrameRequestCallback) =>
    window.setTimeout(() => draw(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", (frame: number) => window.clearTimeout(frame));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  forgetHeatmapReads();
  document.body.innerHTML = "";
});

describe("the button", () => {
  it("appears once /report/me says yes, asked once whatever the page does", async () => {
    const fetch = serve(yes);
    const router = mount();
    expect(await screen.findByRole("button", { name: "Heatmap" })).toBeVisible();
    await act(() => router.navigate("/league/352490"));
    await act(() => router.navigate(`${MEMBER}/what-if`));
    expect(screen.getByRole("button", { name: "Heatmap" })).toBeVisible();
    expect(asked(fetch, "/api/v1/usage/report/me")).toBe(1);
    expect(asked(fetch, "/api/v1/usage/report")).toBe(0);
  });

  it.each([
    ["refused", () => Response.json({ error: "access_refused" }, { status: 403 })],
    ["not configured", () => Response.json({ error: "report_not_configured" }, { status: 503 })],
    ["not JSON", () => new Response("<!doctype html>")],
  ])("stays away when the answer is %s", async (_name, me) => {
    const fetch = serve(me);
    mount();
    await waitFor(() => expect(asked(fetch, "/api/v1/usage/report/me")).toBe(1));
    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Heatmap" })).toBeNull();
  });

  it("is not offered on the admin page itself", async () => {
    const fetch = serve(yes);
    mount("/admin/usage");
    await waitFor(() => expect(asked(fetch, "/api/v1/usage/report/me")).toBe(1));
    await act(async () => {});
    expect(screen.queryByRole("button", { name: "Heatmap" })).toBeNull();
  });
});

describe("the drawing", () => {
  it("reads the range once and draws the page's zones in cells over their boxes", async () => {
    const fetch = serve(yes);
    zone("decision", { left: 0, top: 0, width: 200, height: 400 });
    zone("pitch", { left: 0, top: 400, width: 100, height: 100 });
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Heatmap" }));
    const panel = screen.getByRole("region", { name: "Clicks on this page" });
    expect(panel).toHaveTextContent("Page: member, tool: week");
    // This browser reads as a phone, so the phone's clicks come first.
    expect(screen.getByRole("button", { name: "Phone" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("75 clicks drawn")).toBeVisible();
    // The click in no zone is counted here, never drawn.
    expect(screen.getByText("Outside zones: 3 clicks")).toBeVisible();
    expect(screen.queryByText(/does not name the tool/)).toBeNull();

    const layer = document.querySelector<HTMLElement>("[data-heatmap] [aria-hidden='true']")!;
    await waitFor(() => expect(layer.children).toHaveLength(3));
    const boxes = [...layer.children].map((cell) => {
      const style = (cell as HTMLElement).style;
      return [style.left, style.top, style.width, style.height];
    });
    expect(boxes).toEqual([
      ["0px", "0px", "10px", "20px"],
      ["10px", "20px", "10px", "20px"],
      ["95px", "495px", "5px", "5px"],
    ]);

    await user.click(screen.getByRole("button", { name: "Rage" }));
    expect(await screen.findByText("6 clicks drawn")).toBeVisible();
    expect(screen.queryByText(/Outside zones/)).toBeNull();
    await waitFor(() => expect(layer.children).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "28 days" }));
    await user.click(screen.getByRole("button", { name: "7 days" }));
    await user.click(screen.getByRole("button", { name: "Desktop" }));
    expect(await screen.findByText("No clicks for this choice.")).toBeVisible();
    expect(asked(fetch, "/api/v1/usage/report")).toBe(2);
    const ranges = fetch.mock.calls
      .map(([url]) => url)
      .filter((url) => url.startsWith("/api/v1/usage/report?"));
    expect(new Set(ranges).size).toBe(2);
  });

  it("draws only the clicks of the tool the address names", async () => {
    serve(yes);
    zone("decision", { left: 0, top: 0, width: 200, height: 400 });
    zone("pitch", { left: 0, top: 400, width: 100, height: 100 });
    mount(`${MEMBER}/chips`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Heatmap" }));
    expect(screen.getByRole("region")).toHaveTextContent("Page: member, tool: chips");
    expect(await screen.findByText("7 clicks drawn")).toBeVisible();
    const layer = document.querySelector<HTMLElement>("[data-heatmap] [aria-hidden='true']")!;
    await waitFor(() => expect(layer.children).toHaveLength(1));
    expect(screen.queryByText(/Outside zones/)).toBeNull();
  });

  it("draws an older report's rows, with no tool, on their page alone, and says so", async () => {
    const older = () => {
      const report = usageReportFixture() as unknown as {
        behaviour: { clicks: Record<string, unknown>[] };
      };
      for (const cell of report.behaviour.clicks) delete cell.tool;
      return report;
    };
    serve(yes, older);
    zone("decision", { left: 0, top: 0, width: 200, height: 400 });
    mount(`${MEMBER}/chips`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Heatmap" }));
    expect(await screen.findByText("82 clicks drawn")).toBeVisible();
    expect(screen.getByText(/does not name the tool/)).toBeVisible();
  });

  it("closes and leaves nothing drawn", async () => {
    serve(yes);
    zone("decision", { left: 0, top: 0, width: 200, height: 400 });
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Heatmap" }));
    await screen.findByText("75 clicks drawn");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region")).toBeNull();
    expect(document.querySelector("[data-heatmap] [aria-hidden='true']")).toBeNull();
    expect(screen.getByRole("button", { name: "Heatmap" })).toBeVisible();
  });
});
