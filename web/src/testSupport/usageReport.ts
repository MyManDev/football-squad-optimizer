import type { UsageReport } from "../data/usageAdmin";

const zeroDepth = () =>
  Object.fromEntries(
    ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"].map((d) => [d, 0]),
  );
const zeroDwell = () =>
  Object.fromEntries(["s5", "s15", "s30", "s60", "s180", "s600", "long"].map((d) => [d, 0]));

/**
 * A usage report as the Worker answers it (`scripts/usage_report.mjs --json`), with figures
 * chosen so each section's numbers are distinct on the page.
 */
export function usageReportFixture(): UsageReport {
  return {
    from: "2026-11-10",
    to: "2026-11-16",
    truncated: false,
    events: 1234,
    visits: 321,
    pages: [
      { name: "member", events: 700, visits: 210 },
      { name: "league", events: 150, visits: 95 },
    ],
    tools: [
      { name: "week", events: 400, visits: 180 },
      { name: "what-if", events: 77, visits: 41 },
    ],
    steps: [
      { name: "open", events: 900, visits: 300 },
      { name: "picker_shown", events: 130, visits: 120 },
      { name: "picker_claimed", events: 95, visits: 90 },
      { name: "tool", events: 480, visits: 222 },
      { name: "device_solve", events: 17, visits: 13 },
    ],
    languages: [
      { name: "tr", events: 1100, visits: 290 },
      { name: "en", events: 134, visits: 31 },
    ],
    devices: [
      { name: "phone", events: 900, visits: 240 },
      { name: "desktop", events: 334, visits: 80 },
    ],
    picker: { shown: 120, claimed: 84, left: 36 },
    device_solves: { events: 17, visits: 13 },
    behaviour: {
      events: 5000,
      visits: 310,
      clicks: [
        {
          page: "member",
          device: "phone",
          zone: "decision",
          cell: 0,
          events: 40,
          marks: { none: 30, rage: 6, dead: 4 },
          targets: { control: 35, plain: 5 },
        },
        {
          page: "member",
          device: "phone",
          zone: "decision",
          cell: 21,
          events: 10,
          marks: { none: 10, rage: 0, dead: 0 },
          targets: { control: 2, plain: 8 },
        },
        {
          page: "member",
          device: "phone",
          zone: "pitch",
          cell: 399,
          events: 25,
          marks: { none: 20, rage: 0, dead: 5 },
          targets: { control: 0, plain: 25 },
        },
        {
          page: "member",
          device: "desktop",
          zone: "squad",
          cell: 5,
          events: 9,
          marks: { none: 9, rage: 0, dead: 0 },
          targets: { control: 9, plain: 0 },
        },
        {
          page: "league",
          device: "phone",
          zone: "member-table",
          cell: 3,
          events: 12,
          marks: { none: 12, rage: 0, dead: 0 },
          targets: { control: 12, plain: 0 },
        },
      ],
      frustration: [
        { page: "member", zone: "decision", clicks: 50, rage: 6, dead: 4 },
        { page: "member", zone: "pitch", clicks: 25, rage: 0, dead: 5 },
        { page: "member", zone: "squad", clicks: 9, rage: 0, dead: 0 },
        { page: "league", zone: "member-table", clicks: 12, rage: 0, dead: 0 },
      ],
      scroll: [
        {
          page: "member",
          device: "phone",
          events: 200,
          depth: { ...zeroDepth(), "0": 20, "50": 80, "100": 100 },
          dwell: { ...zeroDwell(), s5: 50, s60: 150 },
        },
        {
          page: "league",
          device: "phone",
          events: 10,
          depth: { ...zeroDepth(), "100": 10 },
          dwell: { ...zeroDwell(), s15: 10 },
        },
      ],
      vitals: [
        {
          metric: "lcp",
          page: "member",
          device: "phone",
          events: 150,
          ratings: { good: 0.6, needs: 0.3, poor: 0.1 },
          p75: 3100,
        },
        {
          metric: "cls",
          page: "member",
          device: "phone",
          events: 140,
          ratings: { good: 0.9, needs: 0.05, poor: 0.05 },
          p75: 80,
        },
      ],
      errors: [{ error: "chunk", page: "member", events: 7, visits: 6 }],
      arrivals: {
        sources: [
          { name: "whatsapp", events: 140, visits: 140 },
          { name: "direct", events: 120, visits: 120 },
        ],
        visits: [
          { name: "new", events: 100, visits: 100 },
          { name: "same_week", events: 60, visits: 60 },
          { name: "last_week", events: 30, visits: 30 },
          { name: "weeks_2_4", events: 6, visits: 6 },
          { name: "older", events: 4, visits: 4 },
          { name: "unknown", events: 50, visits: 50 },
        ],
      },
    },
  };
}

/** The same report with nothing in it. */
export function emptyUsageReportFixture(): UsageReport {
  const report = usageReportFixture();
  return {
    ...report,
    events: 0,
    visits: 0,
    pages: [],
    tools: [],
    steps: [],
    languages: [],
    devices: [],
    picker: { shown: 0, claimed: 0, left: 0 },
    device_solves: { events: 0, visits: 0 },
    behaviour: {
      events: 0,
      visits: 0,
      clicks: [],
      frustration: [],
      scroll: [],
      vitals: [],
      errors: [],
      arrivals: { sources: [], visits: [] },
    },
  };
}
