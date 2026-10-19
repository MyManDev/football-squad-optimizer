import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { SquadCard } from "./SquadCard";

const ENTRY = 35249001;
const view = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;

let fetchSpy: ReturnType<typeof vi.fn>;
let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  let made = 0;
  createObjectURL = vi.fn(() => `blob:card-${(made += 1)}`);
  revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const png = async (_svg: string, _width: number, _height: number) =>
  new Blob(["png"], { type: "image/png" });

function renderCard(draw = vi.fn(png)) {
  render(
    <LanguageProvider initialLanguage="tr">
      <SquadCard view={view} squad={squad} draw={draw} />
    </LanguageProvider>,
  );
  return draw;
}

/** A drawing that finishes only when the test says so. */
function heldDraw() {
  let finish: () => void = () => undefined;
  const draw = vi.fn(
    (_svg: string, _width: number, _height: number) =>
      new Promise<Blob>((resolve) => {
        finish = () => resolve(new Blob(["png"], { type: "image/png" }));
      }),
  );
  return { draw, finish: () => finish() };
}

it("draws the card from the fields the member picked, on the device", async () => {
  const draw = renderCard();
  const transfers = screen.getByRole("checkbox", { name: "Transferler" });
  expect(transfers).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Beklenen puan" })).not.toBeChecked();
  fireEvent.click(transfers);
  fireEvent.click(screen.getByRole("checkbox", { name: "Beklenen puan" }));
  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));

  const preview = await screen.findByRole("img", { name: `${view.gameweek}. hafta kadro kartı` });
  expect(preview).toHaveAttribute("src", "blob:card-1");
  const [svg, width, height] = draw.mock.calls[0]!;
  expect(svg).not.toContain(">Transferler<");
  expect(svg).toContain(">Beklenen puan<");
  expect(width).toBe(1080);
  expect(height).toBeGreaterThan(0);
  const save = screen.getByRole("link", { name: "Kaydet" });
  expect(save).toHaveAttribute("download", `squadopt-gw${view.gameweek}.png`);
  expect(fetchSpy).not.toHaveBeenCalled();
});

it("keeps the focus while drawing, then moves it to the card and says it is ready", async () => {
  const { draw, finish } = heldDraw();
  renderCard(draw);
  const make = screen.getByRole("button", { name: "Kartı oluştur" });
  make.focus();
  fireEvent.click(make);

  const drawing = screen.getByRole("button", { name: "Kart çiziliyor" });
  expect(drawing).toBe(make);
  expect(drawing).not.toBeDisabled();
  expect(drawing).toHaveAttribute("aria-disabled", "true");
  expect(drawing).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent("");
  // A second press while the card is drawn starts no second drawing.
  fireEvent.click(drawing);
  expect(draw).toHaveBeenCalledTimes(1);

  await act(async () => finish());
  const preview = await screen.findByRole("img");
  await waitFor(() => expect(preview).toHaveFocus());
  expect(screen.getByRole("status")).toHaveTextContent("Kart hazır.");
  expect(screen.getByRole("button", { name: "Kartı oluştur" })).toHaveAttribute(
    "aria-disabled",
    "false",
  );
});

it("forgets the drawn card when the member changes the fields", async () => {
  renderCard();
  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("checkbox", { name: "Kaptan" }));
  await waitFor(() => expect(screen.queryByRole("img")).toBeNull());
  expect(screen.queryByRole("link", { name: "Kaydet" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("");
});

it("keeps one object URL, for the card on screen, and lets it go on a redraw and on leaving", async () => {
  const { unmount } = render(
    <LanguageProvider initialLanguage="tr">
      <SquadCard view={view} squad={squad} draw={vi.fn(png)} />
    </LanguageProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));
  expect(await screen.findByRole("img")).toHaveAttribute("src", "blob:card-1");
  expect(revokeObjectURL).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));
  await waitFor(() => expect(screen.getByRole("img")).toHaveAttribute("src", "blob:card-2"));
  expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:card-1");

  unmount();
  expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  expect(revokeObjectURL).toHaveBeenLastCalledWith("blob:card-2");
});

it("says so when the card cannot be drawn", async () => {
  renderCard(vi.fn(async () => Promise.reject(new Error("no canvas"))));
  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Kart çizilemedi.");
});

it("offers no card for a plan without an eleven", () => {
  render(
    <LanguageProvider initialLanguage="en">
      <SquadCard view={{ ...view, starting_xi: null }} squad={squad} />
    </LanguageProvider>,
  );
  expect(screen.getByText("This plan carries no eleven for a card.")).toBeInTheDocument();
  expect(screen.queryByRole("button")).toBeNull();
});
