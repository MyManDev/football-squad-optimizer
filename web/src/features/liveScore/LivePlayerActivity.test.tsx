import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { LivePlayerActivity } from "./LivePlayerActivity";
import type { PlayerActivity } from "./playerActivity";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("expires the event marker so an old event cannot replay after a motion preference change", () => {
  vi.useFakeTimers();
  const { container, rerender } = render(view(0, 0));
  rerender(view(1, 1));
  expect(container.querySelector("[data-live-highlight]")).not.toBeNull();
  act(() => {
    vi.advanceTimersByTime(400);
  });
  expect(container.querySelector("[data-live-highlight]")).toBeNull();
  rerender(view(1, 2));
  expect(container.querySelector("[data-live-highlight]")).toBeNull();
});

const names = new Map([
  [1, "Salah"],
  [2, "Isak"],
]);
const player = (goals: number): PlayerActivity => ({
  elementId: 1,
  matchInProgress: true,
  goals,
  assists: 0,
  appearances: [{ element_id: 1, fixture_id: 91, minutes: 40, goals, assists: 0 }],
});
const view = (goals: number, minute: number) => (
  <LanguageProvider initialLanguage="tr">
    <LivePlayerActivity
      identity="entry:9"
      sourceTime={`2026-10-31T16:0${minute}:00Z`}
      players={[player(goals)]}
      names={names}
    />
  </LanguageProvider>
);

it("shows a static match marker and highlights a new event once without replaying a reread", () => {
  const { container, rerender } = render(view(1, 0));
  expect(screen.getByRole("img", { name: "Maç sürüyor" })).toBeInTheDocument();
  expect(screen.getByLabelText("Gol: 1")).toBeInTheDocument();
  expect(container.querySelector("[data-live-highlight]")).toBeNull();
  rerender(view(2, 1));
  const highlighted = container.querySelector("[data-live-highlight]");
  expect(highlighted).toHaveAttribute("data-live-highlight", "1");
  rerender(view(2, 2));
  expect(container.querySelector("[data-live-highlight]")).toBe(highlighted);
  expect(screen.getByLabelText("Gol: 2")).toBeInTheDocument();
});

it("shows the same final counts instantly under reduced motion", () => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const { container, rerender } = render(view(0, 0));
  rerender(view(1, 1));
  expect(screen.getByLabelText("Gol: 1")).toBeInTheDocument();
  expect(container.querySelector("[data-live-highlight]")).toBeNull();
});

it("shows no empty activity list", () => {
  const quiet = { ...player(0), matchInProgress: false };
  const { container } = render(
    <LanguageProvider initialLanguage="en">
      <LivePlayerActivity
        identity="entry:9"
        sourceTime="2026-10-31T16:00:00Z"
        players={[quiet]}
        names={names}
      />
    </LanguageProvider>,
  );
  expect(container).toBeEmptyDOMElement();
});
