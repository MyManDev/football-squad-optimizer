import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { RivalEntryInput } from "./RivalEntryInput";

afterEach(cleanup);
it.each(["tr", "en"] as const)("selects one listed member only after submit (%s)", (language) => {
  const copy = MESSAGES[language].leagueMembers;
  const select = vi.fn();
  render(
    <LanguageProvider initialLanguage={language}>
      <RivalEntryInput
        members={mockLeagueMembersEnvelope.payload.members}
        entryId={35249001}
        onSelect={select}
      />
    </LanguageProvider>,
  );
  const input = screen.getByLabelText(copy.rivalEntryLabel);
  for (const value of ["35249001", "99999999", "3e7", "abc"]) {
    fireEvent.change(input, { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: copy.rivalEntryChoose }));
    expect(screen.getByRole("alert")).toHaveTextContent(copy.rivalEntryNotListed);
    expect(select).not.toHaveBeenCalled();
  }
  fireEvent.change(input, { target: { value: "35249002" } });
  expect(select).not.toHaveBeenCalled();
  fireEvent.submit(input.closest("form")!);
  expect(select).toHaveBeenCalledExactlyOnceWith(35249002);
  expect(screen.queryByRole("alert")).toBeNull();
});
