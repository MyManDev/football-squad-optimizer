import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DeadlineCalendar } from "./DeadlineCalendar";
import { FIXTURES_COPY } from "./fixturesCopy";
import type { FixturesPayload } from "./types";

const payload: FixturesPayload = {
  season: "2026-27",
  source_snapshot_id: "fpl-live-synthetic",
  captured_at_utc: "2026-10-27T10:00:00Z",
  current_gameweek: 9,
  unscheduled_count: 0,
  gameweeks: [
    { gameweek: 8, deadline_utc: "2026-10-23T17:30:00Z", fixtures: [] },
    { gameweek: 9, deadline_utc: "2026-10-31T11:00:00Z", fixtures: [] },
  ],
};

let createObjectURL: ReturnType<typeof vi.fn>;
let revokeObjectURL: ReturnType<typeof vi.fn>;
let clicked: { href: string; download: string; attached: boolean }[];

beforeEach(() => {
  vi.useFakeTimers({ now: Date.parse("2026-10-28T09:00:00Z"), toFake: ["Date", "setTimeout"] });
  createObjectURL = vi.fn(() => "blob:deadlines");
  revokeObjectURL = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });
  // jsdom cannot follow a download; the link the click would follow is recorded instead.
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push({ href: this.href, download: this.download, attached: this.isConnected });
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("downloads the deadlines ahead as squadopt-deadlines.ics, in the page's language", async () => {
  render(<DeadlineCalendar payload={payload} copy={FIXTURES_COPY.tr} />);
  const button = screen.getByRole("button", { name: FIXTURES_COPY.tr.calendarAction });
  expect(createObjectURL).not.toHaveBeenCalled();

  fireEvent.click(button);

  expect(createObjectURL).toHaveBeenCalledTimes(1);
  const blob = createObjectURL.mock.calls[0]![0] as Blob;
  expect(blob.type).toBe("text/calendar;charset=utf-8");
  const file = (await blob.text()).replace(/\r\n /g, "");
  expect(file.match(/BEGIN:VEVENT/g)).toHaveLength(1);
  expect(file).toContain("\r\nUID:2026-27-gw9-deadline@squadopt\r\n");
  // Numbered from the moment of the click, so a later download replaces this one.
  expect(file).toContain("\r\nSEQUENCE:29886300\r\nDTSTAMP:20261028T090000Z\r\n");
  expect(file).toContain("\r\nDTSTART:20261031T110000Z\r\n");
  expect(file).toContain("\r\nSUMMARY:FPL 9. hafta son tarihi\r\n");
  expect(file).toContain(
    `\r\nDESCRIPTION:Deadline'dan önce SquadOpt'u açın: ${window.location.origin}/\r\n`,
  );

  expect(clicked).toEqual([
    { href: "blob:deadlines", download: "squadopt-deadlines.ics", attached: true },
  ]);
  expect(document.querySelector('a[download="squadopt-deadlines.ics"]')).toBeNull();
  // The URL is let go once the browser has had the file.
  expect(revokeObjectURL).not.toHaveBeenCalled();
  vi.advanceTimersByTime(40_000);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:deadlines");
});

it("offers nothing once no deadline is ahead", () => {
  vi.setSystemTime(Date.parse("2026-11-01T00:00:00Z"));
  const { container } = render(<DeadlineCalendar payload={payload} copy={FIXTURES_COPY.en} />);
  expect(container).toBeEmptyDOMElement();
});
