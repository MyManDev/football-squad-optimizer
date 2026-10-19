import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { SquadCard } from "./SquadCard";

const ENTRY = 35249001;
const view = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1).payload;
const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:card"),
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderCard(draw = vi.fn(async () => new Blob(["png"], { type: "image/png" }))) {
  render(
    <LanguageProvider initialLanguage="tr">
      <SquadCard view={view} squad={squad} draw={draw} />
    </LanguageProvider>,
  );
  return draw;
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
  expect(preview).toHaveAttribute("src", "blob:card");
  const [svg, width, height] = draw.mock.calls[0]!;
  expect(svg).not.toContain(">Transferler<");
  expect(svg).toContain(">Beklenen puan<");
  expect(width).toBe(1080);
  expect(height).toBeGreaterThan(0);
  const save = screen.getByRole("link", { name: "Kaydet" });
  expect(save).toHaveAttribute("download", `squadopt-gw${view.gameweek}.png`);
  expect(fetchSpy).not.toHaveBeenCalled();
});

it("forgets the drawn card when the member changes the fields", async () => {
  renderCard();
  fireEvent.click(screen.getByRole("button", { name: "Kartı oluştur" }));
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("checkbox", { name: "Kaptan" }));
  await waitFor(() => expect(screen.queryByRole("img")).toBeNull());
  expect(screen.queryByRole("link", { name: "Kaydet" })).toBeNull();
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
