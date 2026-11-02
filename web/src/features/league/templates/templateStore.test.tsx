/** Templates: named selections, applied through the URL, stored where the viewer is. */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import type { EntryView } from "../types";
import { TemplatePicker } from "./TemplatePicker";
import { builtinTemplates, LocalTemplateStore, type GameTemplate } from "./templateStore";

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
/** Mert Işık of Half Space, in the example league's list. */
const RIVAL = 35249002;

function Selection() {
  const [params] = useSearchParams();
  return (
    <output data-testid="selection">
      {params.get("mode") ?? "-"}/{params.get("window") ?? "-"}/{params.get("rival") ?? "-"}
    </output>
  );
}

function renderPicker(
  initial = "/league/352490/members/1",
  members: readonly EntryView[] = MEMBERS,
  language: Language = "tr",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <TemplatePicker members={members} />
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

    // One compact row of chips, named like a field and not a card with a heading of its own.
    const row = screen.getByRole("group", { name: "Oyun şablonları" });
    expect(screen.queryByRole("heading")).toBeNull();
    const keep = within(row).getByRole("button", { name: /Farkı koru/ });
    // A builtin is named by its strategy, so the chip adds only its window.
    expect(within(keep).getByText("1 hafta")).toBeInTheDocument();
    fireEvent.click(keep);

    // The standings neighbour is the producer's default: no rival parameter.
    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/1/-");
  });

  it("applies and saves a named rival with the template", () => {
    renderPicker(`/league/352490/members/1?mode=fark-yarat&window=1&rival=${RIVAL}`);

    fireEvent.change(screen.getByLabelText("Bu kombinasyonu adlandır"), {
      target: { value: "Derbi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Seçimi kaydet" }));
    expect(new LocalTemplateStore().list()[0]).toMatchObject({
      strategy: "fark-yarat",
      window: 1,
      rival: RIVAL,
    });

    fireEvent.click(screen.getByRole("button", { name: /En çok puan/ }));
    expect(screen.getByTestId("selection").textContent).toBe("saf-puan/1/-");
    fireEvent.click(screen.getByRole("button", { name: /Derbi.*Mert Işık/ }));
    expect(screen.getByTestId("selection").textContent).toBe(`fark-yarat/1/${RIVAL}`);
  });

  it("saves the current selection under a name and can remove it again", () => {
    renderPicker("/league/352490/members/1?mode=ortak-koru&window=1");

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

describe.each([
  ["tr", "Farkı kapat · 1h"],
  ["en", "Close the gap · 1w"],
] as const)("a saved template's rival in %s", (language, meta) => {
  /** What the saved template's chip says, its name and then its selection. */
  function savedChip(rival: GameTemplate["rival"], members: readonly EntryView[] = MEMBERS) {
    new LocalTemplateStore().save({
      id: "own:derbi",
      name: "Derbi",
      strategy: "fark-yarat",
      window: 1,
      rival,
    });
    renderPicker(undefined, members, language);
    return screen.getByRole("button", { name: new RegExp(`Derbi.*${meta}`) }).textContent;
  }

  /** The league's list with the rival's names as given. */
  const namedAs = (manager_name: string | null, team_name: string | null): EntryView[] =>
    MEMBERS.map((member) =>
      member.entry_id === RIVAL ? { ...member, manager_name, team_name } : member,
    );

  it("is the member's name from the list, with no number", () => {
    expect(savedChip(RIVAL)).toBe(`Derbi${meta} · Mert Işık`);
  });

  it("is the team's name where the list holds no manager's", () => {
    expect(savedChip(RIVAL, namedAs(null, "Half Space"))).toBe(`Derbi${meta} · Half Space`);
  });

  it("is left out where the list does not hold the member", () => {
    expect(savedChip(99999999)).toBe(`Derbi${meta}`);
  });

  it("is left out where the list holds the member with no name", () => {
    expect(savedChip(RIVAL, namedAs(null, null))).toBe(`Derbi${meta}`);
  });

  it("is the team's name where the list holds the manager under the entry stand-in", () => {
    expect(savedChip(RIVAL, namedAs(`entry-${RIVAL}`, "Half Space"))).toBe(
      `Derbi${meta} · Half Space`,
    );
  });

  it("is left out where the list holds only the entry stand-in", () => {
    expect(savedChip(RIVAL, namedAs(`entry-${RIVAL}`, `entry-${RIVAL}`))).toBe(`Derbi${meta}`);
  });

  it("is the team's name where the list holds an empty manager's name", () => {
    expect(savedChip(RIVAL, namedAs("", "Half Space"))).toBe(`Derbi${meta} · Half Space`);
  });

  it("is left out where the list holds an empty name", () => {
    expect(savedChip(RIVAL, namedAs("", null))).toBe(`Derbi${meta}`);
  });

  it("stays the standings neighbour's label for the neighbour", () => {
    expect(savedChip("nearest_above")).toBe(
      `Derbi${meta} · ${MESSAGES[language].leagueMembers.computeRivalNearest}`,
    );
  });
});
