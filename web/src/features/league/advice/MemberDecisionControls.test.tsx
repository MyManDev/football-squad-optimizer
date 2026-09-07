/**
 * The member's controls name only what the producer computed: the catalogue's
 * strategies, the league's rivals with the producer's default marked, one-week windows.
 * Everything else is shown disabled with its reason, never hidden.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { EntryAdviceIndex } from "../types";
import { MemberDecisionControls } from "./MemberDecisionControls";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;

function Selection() {
  const [params] = useSearchParams();
  return (
    <output data-testid="selection">
      {params.get("mode") ?? "-"}/{params.get("window") ?? "-"}/{params.get("rival") ?? "-"}
    </output>
  );
}

function renderControls(
  initial = `/league/members/${ENTRY}`,
  index: EntryAdviceIndex | null = mockEntryAdviceIndex(ENTRY).payload,
  language: "tr" | "en" = "tr",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <MemberDecisionControls entryId={ENTRY} members={MEMBERS} index={index} />
        <Selection />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("member decision controls", () => {
  it("offers the three member strategies and writes the choice to the URL", () => {
    renderControls();
    expect(screen.getByDisplayValue("saf-puan")).toBeChecked();
    expect(screen.queryByRole("combobox")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Ortak çekirdeği koru/ }));

    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/-/-");
    expect(screen.getByRole("combobox", { name: "Karşısında oynadığın üye" })).toBeInTheDocument();
  });

  it("marks the producer's default rival and drops the parameter when it is chosen again", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const other = index.rival_entry_ids.find((id) => id !== index.default_rival_entry_id)!;
    renderControls(`/league/members/${ENTRY}?mode=fark-yarat`);

    const select = screen.getByRole("combobox", { name: "Karşısında oynadığın üye" });
    expect(select).toHaveValue(String(index.default_rival_entry_id));
    expect(screen.getByRole("option", { name: /\(sıralamada hemen üstün\)/ })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: String(other) } });
    expect(screen.getByTestId("selection").textContent).toBe(`fark-yarat/-/${other}`);

    fireEvent.change(select, { target: { value: String(index.default_rival_entry_id) } });
    expect(screen.getByTestId("selection").textContent).toBe("fark-yarat/-/-");
  });

  it("labels a pair the producer could not compute", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const missing = index.unavailable[0]!;
    renderControls(`/league/members/${ENTRY}?mode=${missing.strategy}`);
    const option = screen.getByRole("option", { name: /\(hesaplanamadı\)/ });
    expect(option).toHaveValue(String(missing.rival_entry_id));
  });

  it("keeps the longer windows visible but disabled, with the reason", () => {
    renderControls();
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeDisabled();
    expect(screen.getByText(/çok haftalı projeksiyon bu yol için ölçülmedi/)).toBeInTheDocument();
  });

  it("falls back to the league's members as rivals when no index was published", () => {
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru`, null, "en");
    const select = screen.getByRole("combobox", { name: "The member you are playing against" });
    const humans = MEMBERS.filter((m) => m.member_kind === "human" && m.entry_id !== ENTRY);
    expect(screen.getAllByRole("option")).toHaveLength(humans.length);
    expect(select).toHaveValue(String(humans[0]!.entry_id));
  });

  it("never shows a probability or a chance, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      const { container, unmount } = renderControls(
        `/league/members/${ENTRY}?mode=ortak-koru`,
        undefined,
        language,
      );
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/%|probabilit|olasılık|\bP\(/i);
      expect(text).not.toMatch(/chance of falling behind|geride kalma ihtimalini/i);
      unmount();
    }
  });
});
