import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";
import type { UsageReport } from "../../data/usageAdmin";
import { USAGE_ADMIN_KEY } from "../../data/usageAdminFlag";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { Language } from "../../i18n/messages";
import { emptyUsageReportFixture, usageReportFixture } from "../../testSupport/usageReport";
import { UsageAdminPage } from "./UsageAdminPage";

type Answer = () => Response;

function serve(answer: Answer = () => Response.json(usageReportFixture())) {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) => answer());
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const reportJson = (report: UsageReport) => () => Response.json(report);

function mount(language: Language = "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <QueryClientProvider client={new QueryClient()}>
        <UsageAdminPage />
      </QueryClientProvider>
    </LanguageProvider>,
  );
}

/** The region a Card heading names. */
const region = (name: string) => screen.getByRole("heading", { name }).closest("section")!;

/** Each body row of a region's table, as its cells' text. */
const rows = (name: string) =>
  within(region(name))
    .getAllByRole("row")
    .slice(1)
    .map((row) => [...row.querySelectorAll("th, td")].map((cell) => cell.textContent));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-16T12:00:00Z"));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.removeItem(USAGE_ADMIN_KEY);
  window.history.replaceState(null, "", "/");
});

describe("the range", () => {
  it("starts at the last 7 UTC days and asks the Worker for them", async () => {
    const fetch = serve();
    mount();
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    await screen.findByRole("heading", { name: "Totals" });
    expect(fetch.mock.calls[0]![0]).toBe("/api/v1/usage/report?from=2026-11-10&to=2026-11-16");
    expect(screen.getByLabelText("From")).toHaveValue("2026-11-10");
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-16");
  });

  it("reads today, 28 days and two chosen days", async () => {
    const fetch = serve();
    mount();
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Totals" });
    await user.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() =>
      expect(fetch.mock.calls.at(-1)![0]).toBe(
        "/api/v1/usage/report?from=2026-11-16&to=2026-11-16",
      ),
    );
    await user.click(screen.getByRole("button", { name: "28 days" }));
    await waitFor(() =>
      expect(fetch.mock.calls.at(-1)![0]).toBe(
        "/api/v1/usage/report?from=2026-10-20&to=2026-11-16",
      ),
    );
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01" } });
    await waitFor(() =>
      expect(fetch.mock.calls.at(-1)![0]).toBe(
        "/api/v1/usage/report?from=2026-11-01&to=2026-11-16",
      ),
    );
    expect(screen.getByRole("button", { name: "28 days" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("asks nothing for a range the Worker would refuse", async () => {
    const fetch = serve();
    mount();
    await screen.findByRole("heading", { name: "Totals" });
    const before = fetch.mock.calls.length;
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-20" } });
    expect(screen.getByText(/at most 92 days/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-16" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-01-01" } });
    expect(screen.getByText(/at most 92 days/)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(before);
  });
});

describe("the states", () => {
  it("shows the loading state until the answer comes", async () => {
    let release: (response: Response) => void = () => {};
    const fetch = vi.fn(() => new Promise<Response>((resolve) => (release = resolve)));
    vi.stubGlobal("fetch", fetch);
    mount();
    expect(document.querySelector('[role="status"][aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText("Reading the record")).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    release(Response.json(usageReportFixture()));
    expect(await screen.findByRole("heading", { name: "Totals" })).toBeVisible();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
  });

  it.each([
    [
      "signed out",
      () => {
        const response = new Response(null);
        Object.defineProperty(response, "type", { value: "opaqueredirect" });
        return response;
      },
      "You are not signed in",
      "Reload the page and Cloudflare Access will ask you to sign in.",
    ],
    [
      "refused",
      () => Response.json({ error: "access_refused" }, { status: 403 }),
      "This account may not read the record",
      "Sign in with an address on the admin list, or ask the owner to add yours.",
    ],
    [
      "not configured",
      () => Response.json({ error: "report_not_configured" }, { status: 503 }),
      "The report is not set up yet",
      "The usage Worker has no Access or analytics settings.",
    ],
  ])("says when the reader is %s, and marks nothing", async (_name, answer, title, detail) => {
    serve(answer);
    mount();
    expect(await screen.findByText(title)).toBeVisible();
    expect(screen.getByText(detail)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(localStorage.getItem(USAGE_ADMIN_KEY)).toBeNull();
  });

  it("offers a retry when the read failed", async () => {
    let fail = true;
    const fetch = serve(() =>
      fail ? new Response("<!doctype html>") : Response.json(usageReportFixture()),
    );
    mount();
    expect(await screen.findByText("The record could not be read")).toBeVisible();
    fail = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Totals" })).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("says when the range holds nothing", async () => {
    serve(reportJson(emptyUsageReportFixture()));
    mount();
    expect(await screen.findByText("Nothing recorded in this range")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Totals" })).toBeNull();
  });

  it("says when the row limit cut the range off", async () => {
    serve(reportJson({ ...usageReportFixture(), truncated: true }));
    mount();
    expect(await screen.findByText(/these counts are partial/)).toBeVisible();
  });

  it("marks the browser as an admin's once a report is read", async () => {
    serve();
    mount();
    await screen.findByRole("heading", { name: "Totals" });
    expect(localStorage.getItem(USAGE_ADMIN_KEY)).toBe("1");
  });

  it("asks search engines to leave the page out while it is mounted", async () => {
    serve();
    const { unmount } = mount();
    await screen.findByRole("heading", { name: "Totals" });
    expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow",
    );
    unmount();
    expect(document.head.querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("the sections", () => {
  it("draw the report's numbers", async () => {
    serve();
    mount();
    await screen.findByRole("heading", { name: "Totals" });

    const totals = region("Totals");
    for (const [label, value] of [
      ["Visits", "321"],
      ["Events", "6,234"],
      ["Picker: name taken", "70%"],
      ["Returning visits", "50%"],
      ["Phone visits", "75%"],
      ["Rage and dead clicks", "14.2%"],
    ]) {
      expect(within(totals).getByText(label).nextElementSibling).toHaveTextContent(value!);
    }

    expect(rows("Funnel")).toEqual([
      ["Opened a page", "300", "100%"],
      ["Saw the picker", "120", "40%"],
      ["Took a name", "90", "30%"],
      ["Used a tool", "222", "74%"],
      ["Solved on the device", "13", "4.3%"],
    ]);
    expect(rows("Tools")).toEqual([
      ["week", "180", "400"],
      ["what-if", "41", "77"],
    ]);
    expect(rows("Pages")).toEqual([
      ["member", "210", "700"],
      ["league", "95", "150"],
    ]);
    expect(rows("Sources")).toEqual([
      ["whatsapp", "140", "140"],
      ["Direct", "120", "120"],
    ]);
    expect(rows("Returns")[0]).toEqual(["First visit", "100", "100"]);
    expect(rows("Returns")).toHaveLength(6);

    const depth = rows("Scroll depth");
    expect(depth).toHaveLength(10);
    expect(depth[0]).toEqual(["at least 10% seen", "180", "90%"]);
    expect(depth[5]).toEqual(["at least 60% seen", "100", "50%"]);
    expect(depth[9]).toEqual(["at least 100% seen", "100", "50%"]);
    expect(rows("Time on page")[0]).toEqual(["Under 5 s", "50", "25%"]);
    expect(rows("Time on page")[3]).toEqual(["30 to 60 s", "150", "75%"]);

    expect(rows("Speed (Web Vitals)")).toEqual([
      ["LCP", "member", "Phone", "150", "3,100 msNeeds work", "60%", "30%", "10%"],
      ["CLS", "member", "Phone", "140", "0.08Good", "90%", "5%", "5%"],
    ]);
    expect(rows("Errors")).toEqual([["Failed to load", "member", "7", "6"]]);
    // The member page's tools share page `member`; each tool's zone is a row of its own.
    expect(rows("Clicks by zone")).toEqual([
      ["decision", "week", "50", "6", "4"],
      ["pitch", "week", "25", "0", "5"],
      ["decision", "chips", "7", "0", "0"],
      ["page", "week", "3", "0", "0"],
    ]);
  });

  it("follow the chosen page and device", async () => {
    serve();
    mount();
    await screen.findByRole("heading", { name: "Totals" });
    const clicks = region("Clicks by zone");
    fireEvent.change(within(clicks).getByLabelText("Device"), { target: { value: "desktop" } });
    expect(rows("Clicks by zone")).toEqual([["squad", "week", "9", "0", "0"]]);
    // The scroll section reads the same choice: no desktop scroll was sent.
    expect(within(region("Scroll depth")).getByText("none")).toBeVisible();
    fireEvent.change(within(clicks).getByLabelText("Page"), { target: { value: "league" } });
    fireEvent.change(within(clicks).getByLabelText("Device"), { target: { value: "phone" } });
    expect(rows("Clicks by zone")).toEqual([["member-table", "(no tool)", "12", "0", "0"]]);
    expect(rows("Scroll depth")[9]).toEqual(["at least 100% seen", "10", "100%"]);
  });

  it("speak Turkish", async () => {
    serve();
    mount("tr");
    expect(await screen.findByRole("heading", { name: "Toplamlar" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Bugün" })).toBeVisible();
    expect(screen.getByRole("button", { name: "7 gün" })).toHaveAttribute("aria-pressed", "true");
    expect(within(region("Kaydırma derinliği")).getByText("en az %10 görüldü")).toBeVisible();
  });
});

describe("the route", () => {
  it("opens at /admin/usage and stands in no navigation", async () => {
    serve();
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    window.history.replaceState(null, "", "/admin/usage");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Kullanım kaydı", level: 1 })).toBeVisible();
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href") ?? "").not.toContain("/admin");
    }
  });
});
