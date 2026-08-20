import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisIndex } from "../data";
import { AnalysisPage } from "./AnalysisPage";

const index: AnalysisIndex = {
  contract_version: "web_analysis_index_v1",
  entries: [
    {
      slug: "positive",
      title: "Passing result",
      date: "2026-08-19T12:00:00Z",
      type: "passed",
      phase: "Planning",
      finding: "The declared gate passed.",
      markdown_path: "positive.md",
      json_path: "positive.json",
    },
    {
      slug: "negative",
      title: "Clean negative",
      date: "2026-08-20T12:00:00Z",
      type: "negative",
      phase: "Uncertainty and recalibration",
      finding: "The candidate lost to the baseline.",
      markdown_path: "negative.md",
      json_path: "negative.json",
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderPage(path = "/analysis") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/analysis/:slug" element={<AnalysisPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockAssets() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("index.json")) {
        return { ok: true, status: 200, json: async () => index } as Response;
      }
      return {
        ok: true,
        status: 200,
        text: async () => "# Table report\n\n| arm | score |\n| --- | ---: |\n| control | 1.0 |",
      } as Response;
    }),
  );
}

describe("AnalysisPage", () => {
  it("keeps negative measurements visible in their own tab", async () => {
    mockAssets();
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Passing result")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Negatifler" }));

    expect(screen.getByText("Clean negative")).toBeInTheDocument();
    expect(screen.queryByText("Passing result")).not.toBeInTheDocument();
    expect(screen.getByText("1 / 2 ölçüm gösteriliyor")).toBeInTheDocument();
  });

  it("renders tables from markdown and links the raw JSON", async () => {
    mockAssets();
    renderPage("/analysis/negative");

    expect(await screen.findByRole("heading", { name: "Table report" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ham JSON" })).toHaveAttribute(
      "href",
      "/analysis/negative.json",
    );
  });
});
