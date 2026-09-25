import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../i18n/LanguageProvider";
import { MESSAGES } from "../i18n/messages";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

function Broken(): never {
  throw new Error("chunk failed to load");
}

afterEach(cleanup);

describe("the route error boundary", () => {
  it("keeps the shell and offers a reload when a page throws, then recovers on another address", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={["/broken"]}>
          <nav>
            <Link to="/fine">Menü</Link>
          </nav>
          <RouteErrorBoundary>
            <Routes>
              <Route path="/broken" element={<Broken />} />
              <Route path="/fine" element={<p>Sayfa</p>} />
            </Routes>
          </RouteErrorBoundary>
        </MemoryRouter>
      </LanguageProvider>,
    );
    const copy = MESSAGES.tr.common;
    expect(screen.getByText("Menü")).toBeInTheDocument();
    expect(screen.getByText(copy.pageFailed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.reload })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Menü" }));
    expect(screen.getByText("Sayfa")).toBeInTheDocument();
    expect(screen.queryByText(copy.pageFailed)).toBeNull();
    quiet.mockRestore();
  });
});
