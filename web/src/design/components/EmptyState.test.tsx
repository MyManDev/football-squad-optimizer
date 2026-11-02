import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

afterEach(cleanup);

it("is a quiet line inside a page", () => {
  render(<EmptyState title="Loading" />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading");
  expect(screen.queryByRole("heading")).toBeNull();
});

it("heads the page when it is all the page holds", () => {
  render(<EmptyState page title="Nothing here" />);
  expect(screen.getByRole("heading", { level: 1, name: "Nothing here" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Nothing here");
});
