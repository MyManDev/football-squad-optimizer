import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { LLMOPT_COPY } from "./copy";
import { OwnKeyForm } from "./OwnKeyForm";
import { clearOwnKey, heldModel } from "./ownKey";

const words = LLMOPT_COPY.en.ownKey;
const KEY = "sk-test-unsaved-page-key-0001";

afterEach(() => {
  cleanup();
  clearOwnKey();
});

it("wipes an unsaved key before the page enters the back-forward cache", () => {
  render(<OwnKeyForm copy={LLMOPT_COPY.en} disabled={false} />);
  const key = screen.getByLabelText(words.key);
  const save = screen.getByRole("button", { name: words.save });
  const remove = screen.getByRole("button", { name: words.delete });
  fireEvent.change(screen.getByLabelText(words.model), { target: { value: "gpt-5-mini" } });
  fireEvent.input(key, { target: { value: KEY } });
  expect(save).toBeEnabled();
  expect(remove).toBeEnabled();

  act(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
  act(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
  expect(key).toHaveValue("");
  expect(save).toBeDisabled();
  expect(remove).toBeDisabled();
  expect(heldModel()).toBeNull();

  // Restoring the page still allows a freshly entered key to be held.
  fireEvent.input(key, { target: { value: KEY } });
  fireEvent.click(save);
  expect(heldModel()).toEqual({ provider: "openai", model: "gpt-5-mini" });
  expect(key).toHaveValue("");
});
