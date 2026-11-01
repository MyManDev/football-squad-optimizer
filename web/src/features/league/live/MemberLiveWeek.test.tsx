import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
  type LiveExample,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { withLeague } from "../../../testSupport/league";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { createForwarderClient, type ForwarderClient } from "../forwarder/client";
import type { FplEntryBundle } from "../forwarder/documents";
import { MemberLiveWeek } from "./MemberLiveWeek";
import { memberLiveScore } from "./memberLiveScore";
import type { MemberLiveDependencies } from "./useMemberLiveScore";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!.payload;
const WEEK = SQUAD.gameweek;
const SEASON = SQUAD.season;
const CAPTURE = SQUAD.source_snapshot_id!;
const CALENDAR = exampleCalendar({
  season: SEASON,
  gameweek: WEEK,
  deadline: "2026-08-21T17:30:00Z",
});
const TABLE = exampleTable({ season: SEASON, gameweek: WEEK, capture: CAPTURE });
const MEMBER = exampleMember(ENTRY, WEEK);
const BUNDLE = exampleBundle(ENTRY, WEEK, MEMBER);

/** The forwarder's answers, in the order they are asked, and the reads made. */
function forwarderAnswering(
  bundle: Awaited<ReturnType<ForwarderClient["entryBundle"]>>,
  ...lives: Awaited<ReturnType<ForwarderClient["liveWeek"]>>[]
) {
  const queue = [...lives];
  return {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(async () => bundle),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => queue.shift() ?? queue.at(-1)!),
  };
}

const okBundle = (document: FplEntryBundle = BUNDLE) =>
  ({ ok: true, document, copy: "miss" }) as const;
const okLive = (name: LiveExample) =>
  ({ ok: true, document: forwardedLive(name, WEEK), copy: "miss" }) as const;

const tableLoader = () =>
  vi.fn<NonNullable<MemberLiveDependencies["loadTable"]>>(async () => ({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-08-21T07:00:00Z",
    source_kind: "live",
    payload: TABLE,
  }));

function show(dependencies: MemberLiveDependencies, language: "tr" | "en" = "tr") {
  return render(
    <LanguageProvider initialLanguage={language}>
      {withLeague(<MemberLiveWeek squad={SQUAD} fixtures={CALENDAR} dependencies={dependencies} />)}
    </LanguageProvider>,
  );
}

const expected = (name: LiveExample) => {
  const result = memberLiveScore({
    live: forwardedLive(name, WEEK),
    member: MEMBER,
    table: TABLE,
    fixtures: CALENDAR,
  });
  if (!result.ok) throw new Error(result.reason);
  return result.live.score;
};

const net = () => screen.getByText("Net puan", { exact: true }).nextElementSibling;

describe.each(["tr", "en"] as const)("the member's live week in %s", (language) => {
  it("shows a week in progress, read once on open", async () => {
    const forwarder = forwarderAnswering(okBundle(), okLive("in_progress"));
    const loadTable = tableLoader();
    const { container } = show({ forwarder, loadTable }, language);
    const score = expected("in_progress");
    expect(
      await screen.findByText(language === "tr" ? "Bonus bekleniyor" : "Bonus pending"),
    ).toBeInTheDocument();
    expect(container).toHaveTextContent(`${score.fixtures_finished} / ${score.fixtures_total}`);
    expect(container.querySelector("time")).toHaveAttribute("datetime", score.source_time);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(String(WEEK));
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.textContent).not.toMatch(AS_A_CAVEAT);
    // The bundle for the page's table gameweek, then its current week's live points.
    expect(forwarder.entryBundle).toHaveBeenCalledExactlyOnceWith(ENTRY, WEEK, expect.anything());
    expect(forwarder.liveWeek).toHaveBeenCalledExactlyOnceWith(MEMBER.gameweek, expect.anything());
    expect(loadTable).toHaveBeenCalledTimes(1);
  });

  it("shows a finished week with its bonus added", async () => {
    const forwarder = forwarderAnswering(okBundle(), okLive("finished"));
    const { container } = show({ forwarder, loadTable: tableLoader() }, language);
    const score = expected("finished");
    expect(
      await screen.findByText(language === "tr" ? "Bonus eklendi" : "Bonus added"),
    ).toBeInTheDocument();
    expect(container).toHaveTextContent(`${score.fixtures_total} / ${score.fixtures_total}`);
  });
});

it("shows the scorer's net, and the captain and substitutions by the table's names", async () => {
  const forwarder = forwarderAnswering(okBundle(), okLive("finished"));
  show({ forwarder, loadTable: tableLoader() });
  const score = expected("finished");
  await waitFor(() => expect(net()).toHaveTextContent(new RegExp(`^${score.net}$`)));
  expect(screen.getAllByText(`Player ${score.captain}`).length).toBeGreaterThan(0);
  for (const [out, incoming] of score.autosubs) {
    expect(screen.getByText(`Player ${out}`)).toBeInTheDocument();
    expect(screen.getByText(`Player ${incoming}`)).toBeInTheDocument();
  }
});

describe("no card when the source does not answer", () => {
  /** The site's own client over a transport that answers every route with `answer`. */
  const client = (answer: () => Response) => createForwarderClient({ fetch: async () => answer() });
  const marked = (status: number, error: string) => () =>
    new Response(JSON.stringify({ error }), {
      status,
      headers: { "content-type": "application/json", "x-squadopt-fpl": "1" },
    });
  const shell = () =>
    new Response("<!doctype html><html></html>", {
      status: 200,
      headers: { "content-type": "text/html" },
    });

  it.each([
    ["the forwarder's 404", marked(404, "not_found")],
    ["an entry FPL does not have", marked(404, "entry_not_found")],
    ["the forwarder's 503", marked(503, "upstream_unavailable")],
    ["the site's HTML shell, at 200", shell],
  ])("for %s", async (_, answer) => {
    const forwarder = client(answer);
    const read = vi.spyOn(forwarder, "entryBundle");
    const live = vi.spyOn(forwarder, "liveWeek");
    const loadTable = tableLoader();
    const { container } = show({ forwarder, loadTable });
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
    await read.mock.results[0]!.value;
    expect(container).toBeEmptyDOMElement();
    // Without a bundle nothing more is asked: no live points, no table.
    expect(live).not.toHaveBeenCalled();
    expect(loadTable).not.toHaveBeenCalled();
  });

  it("for a live week the forwarder does not answer", async () => {
    const forwarder = forwarderAnswering(okBundle(), { ok: false, reason: "upstream_unavailable" });
    const { container } = show({ forwarder, loadTable: tableLoader() });
    await waitFor(() => expect(forwarder.liveWeek).toHaveBeenCalledTimes(1));
    await forwarder.liveWeek.mock.results[0]!.value;
    expect(container).toBeEmptyDOMElement();
  });

  it("for a bundle without a current week", async () => {
    const forwarder = forwarderAnswering(okBundle({ ...BUNDLE, current_week: null }));
    const { container } = show({ forwarder, loadTable: tableLoader() });
    await waitFor(() => expect(forwarder.entryBundle).toHaveBeenCalledTimes(1));
    await forwarder.entryBundle.mock.results[0]!.value;
    expect(container).toBeEmptyDOMElement();
    expect(forwarder.liveWeek).not.toHaveBeenCalled();
  });

  it("for a table that cannot be read", async () => {
    const forwarder = forwarderAnswering(okBundle(), okLive("in_progress"));
    const loadTable = vi.fn<NonNullable<MemberLiveDependencies["loadTable"]>>(async () => {
      throw new Error("missing");
    });
    const { container } = show({ forwarder, loadTable });
    await waitFor(() => expect(loadTable).toHaveBeenCalledTimes(1));
    await Promise.allSettled([loadTable.mock.results[0]!.value]);
    await forwarder.liveWeek.mock.results[0]!.value;
    expect(container).toBeEmptyDOMElement();
  });
});

describe("refresh", () => {
  it("reads the live points again on the member's press, and only then", async () => {
    const forwarder = forwarderAnswering(okBundle(), okLive("in_progress"), okLive("finished"));
    const loadTable = tableLoader();
    show({ forwarder, loadTable });
    await screen.findByText("Bonus bekleniyor");
    // No timer reads it again.
    vi.useFakeTimers();
    vi.advanceTimersByTime(30 * 60_000);
    vi.useRealTimers();
    expect(forwarder.liveWeek).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Yenile" }));
    expect(screen.getByRole("button", { name: "Yenileniyor" })).toBeDisabled();
    expect(await screen.findByText("Bonus eklendi")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yenile" })).toBeEnabled();
    // A refresh asks for the live points alone: the bundle and the table are kept.
    expect(forwarder.liveWeek).toHaveBeenCalledTimes(2);
    expect(forwarder.entryBundle).toHaveBeenCalledTimes(1);
    expect(loadTable).toHaveBeenCalledTimes(1);
  });

  it("leaves no card when the refresh is not answered", async () => {
    const forwarder = forwarderAnswering(okBundle(), okLive("in_progress"), {
      ok: false,
      reason: "network",
    });
    const { container } = show({ forwarder, loadTable: tableLoader() });
    fireEvent.click(await screen.findByRole("button", { name: "Yenile" }));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
