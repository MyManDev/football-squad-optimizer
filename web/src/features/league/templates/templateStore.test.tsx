/** Templates: named selections, applied through the URL, stored where the viewer is. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { TemplatePicker } from "./TemplatePicker";
import { builtinTemplates, LocalTemplateStore } from "./templateStore";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

function Selection() {
  const [params] = useSearchParams();
  return (
    <output data-testid="selection">
      {params.get("mode") ?? "-"}/{params.get("window") ?? "-"}/{params.get("rival") ?? "-"}
    </output>
  );
}

function renderPicker(initial = "/league/members/1") {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[initial]}>
        <TemplatePicker />
        <Selection />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the local template store", () => {
  it("round-trips, refuses malformed entries, and never saves a builtin", () => {
    const store = new LocalTemplateStore();
    store.save({ id: "own:x", name: "X", strategy: "garantici", window: 3, rival: 42 });
    store.save({
      id: "builtin:saf-puan:1",
      name: "n",
      strategy: "saf-puan",
      window: 1,
      rival: "nearest_above",
      builtin: true,
    });
    expect(store.list()).toHaveLength(1);
    expect(store.list()[0].rival).toBe(42);

    window.localStorage.setItem("squadopt.templates", "{broken");
    expect(store.list()).toEqual([]);
    window.localStorage.setItem(
      "squadopt.templates",
      JSON.stringify([{ id: "bad", name: " ", strategy: "saf-puan", window: 2, rival: 0 }]),
    );
    expect(store.list()).toEqual([]);
  });

  it("removing by id removes exactly that template", () => {
    const store = new LocalTemplateStore();
    store.save({ id: "own:a", name: "A", strategy: "agresif", window: 1, rival: "nearest_above" });
    store.save({ id: "own:b", name: "B", strategy: "saf-puan", window: 5, rival: "nearest_above" });
    store.remove("own:a");
    expect(store.list().map((t) => t.id)).toEqual(["own:b"]);
  });
});

describe("the picker", () => {
  it("shows one builtin per member strategy and applies through the URL", () => {
    renderPicker();

    fireEvent.click(screen.getByRole("button", { name: /Ortak çekirdeği koru/ }));

    // The standings neighbour is the producer's default: no rival parameter.
    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/1/-");
  });

  it("applies and saves a named rival with the template", () => {
    renderPicker("/league/members/1?mode=fark-yarat&window=1&rival=42");

    fireEvent.change(screen.getByLabelText("Bu kombinasyonu adlandır"), {
      target: { value: "Derbi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Seçimi kaydet" }));
    expect(new LocalTemplateStore().list()[0]).toMatchObject({
      strategy: "fark-yarat",
      window: 1,
      rival: 42,
    });

    fireEvent.click(screen.getByRole("button", { name: /Saf puan/ }));
    expect(screen.getByTestId("selection").textContent).toBe("saf-puan/1/-");
    fireEvent.click(screen.getByRole("button", { name: /Derbi.*#42/ }));
    expect(screen.getByTestId("selection").textContent).toBe("fark-yarat/1/42");
  });

  it("saves the current selection under a name and can remove it again", () => {
    renderPicker("/league/members/1?mode=ortak-koru&window=1");

    fireEvent.change(screen.getByLabelText("Bu kombinasyonu adlandır"), {
      target: { value: "Derbi planım" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Seçimi kaydet" }));

    expect(screen.getAllByRole("button", { name: /Derbi planım/ }).length).toBeGreaterThan(0);
    expect(new LocalTemplateStore().list()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Derbi planım şablonunu kaldır" }));
    expect(new LocalTemplateStore().list()).toHaveLength(0);
  });

  it("builtins cover exactly the member strategies", () => {
    const names = builtinTemplates({ "saf-puan": "a", "ortak-koru": "b", "fark-yarat": "c" });
    expect(names.map((t) => t.strategy)).toEqual(["saf-puan", "ortak-koru", "fark-yarat"]);
    expect(new Set(names.map((t) => t.window))).toEqual(new Set([1]));
    expect(new Set(names.map((t) => t.rival))).toEqual(new Set(["nearest_above"]));
  });
});
