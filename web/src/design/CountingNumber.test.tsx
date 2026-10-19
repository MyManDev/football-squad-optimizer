import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { CountingNumber } from "./CountingNumber";
import { forgetCounts } from "./countMotion";

const tr = (value: number) => value.toFixed(1).replace(".", ",");
const en = (value: number) => value.toFixed(1);

let animate: ReturnType<typeof vi.fn>;
let reduceMotion = false;

beforeEach(() => {
  reduceMotion = false;
  vi.stubGlobal("matchMedia", () => ({ matches: reduceMotion }) as MediaQueryList);
  vi.stubGlobal("requestAnimationFrame", () => 0);
  animate = vi.fn(() => ({
    effect: { getComputedTiming: () => ({ progress: 0 }) },
    playState: "running",
    addEventListener: () => undefined,
    cancel: () => undefined,
  }));
  Object.defineProperty(HTMLElement.prototype, "animate", { value: animate, configurable: true });
});

afterEach(() => {
  cleanup();
  forgetCounts();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as { animate?: unknown }).animate;
});

const figure = (container: HTMLElement) =>
  container.querySelector("[data-counting-number]") as HTMLElement;

it("shows the first value as it is and does not count", () => {
  const { container } = render(<CountingNumber countKey="net:1:7" value={42.5} format={en} />);
  expect(figure(container).textContent).toBe("42.5");
  expect(animate).not.toHaveBeenCalled();
});

it("starts nothing when a re-render keeps the value", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={42.5} format={(value) => en(value)} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("42.5");
});

it("counts once when the value changes", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
  expect(figure(container).textContent).toBe("42.5");
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
});

it("counts from the last value a remounted figure showed under the same key", () => {
  const first = render(<CountingNumber countKey="net:1:7" value={42.5} format={en} />);
  first.unmount();
  render(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
  cleanup();
  render(<CountingNumber countKey="net:2:7" value={30} format={en} />);
  expect(animate).toHaveBeenCalledTimes(1);
});

it("rewrites the same value in a new language without counting", () => {
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={42.5} format={tr} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("42,5");
});

it("writes a new value at once under reduced motion", () => {
  reduceMotion = true;
  const { container, rerender } = render(
    <CountingNumber countKey="net:1:7" value={42.5} format={en} />,
  );
  rerender(<CountingNumber countKey="net:1:7" value={47} format={en} />);
  expect(animate).not.toHaveBeenCalled();
  expect(figure(container).textContent).toBe("47.0");
});
