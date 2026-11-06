/**
 * #983 step 4, one FPL team's page through the forwarder: at `/entry/<id>` on its own, and
 * as a member chosen from a forwarded league's table. The newest capture table the directory
 * names is read, the team's bundle is asked for its gameweek, and the identity rule binds
 * the two. Bound, the device solves the one-week plan on opening; not bound, the page says
 * the plan cannot be computed this week and shows nothing else.
 */

import { createHash } from "node:crypto";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import deviceInstances from "../../../fixtures/device-plan/instances.json";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import {
  bundleHolding,
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  fixtureCaptureTable,
  forwardedLive,
  STANDINGS_EXAMPLES,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { jsonResponse, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import { COMPUTE_COPY } from "../advice/computeCopy";
import type { AdviceClient, AdviceRequestResult } from "../advice/adviceClient";
import type { DevicePlanReply, DevicePlanRequest } from "../device/deviceSolver.worker";
import type { DeviceSolver } from "../device/useDevicePlan";
import type { FplEntryBundle } from "../forwarder/documents";
import { ForwardedLeagueContext } from "./ForwardedLeagueContext";
import { ForwardedMemberPage, type ForwardedMemberDependencies } from "./ForwardedMemberPage";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const OLDER = "fpl-live-20261009T060000Z-ba9876543210";
const TABLE = fixtureCaptureTable(CAPTURE);
const member = deviceInstances.members[2]!;
const ENTRY = member.entry_id;
const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
const WORTH = Object.values(member.entry.sell_tenths).reduce((sum, price) => sum + price, 0);
const BUNDLE = bundleHolding(ENTRY, TABLE.gameweek, FIFTEEN, {
  bank: member.entry.bank_tenths,
  value: member.entry.bank_tenths + WORTH,
  captain: 132,
  vice: 139,
});

function text(value: unknown): string {
  return JSON.stringify(value);
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function envelope(payload: unknown, contract = "provisional_league_ui_v1") {
  return {
    contract_version: contract,
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload,
  };
}

const TABLE_BYTES = text(envelope(TABLE));
const OLDER_BYTES = text(envelope({ ...TABLE, gameweek: 6, source_snapshot_id: OLDER }));

/** A directory line of `gameweek` naming the capture's table at `bytes`. */
function line(leagueId: number, gameweek: number, capture: string, bytes: string) {
  return {
    league_id: leagueId,
    league_name: `League ${leagueId}`,
    season: "2026-27",
    gameweek,
    path: `leagues/${leagueId}`,
    device_plan: `device/${capture}/device-plan.json`,
    device_plan_sha256: sha256(bytes),
  };
}

/** An answer of the forwarder: JSON with its mark. */
function marked(value: unknown, status = 200): Response {
  return new Response(text(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-squadopt-fpl": "1" },
  });
}

const OPEN_WEEK = envelope(
  {
    season: TABLE.season,
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: TABLE.gameweek - 1,
    unscheduled_count: 0,
    gameweeks: [{ gameweek: TABLE.gameweek, deadline_utc: "2999-01-01T00:00:00Z", fixtures: [] }],
  },
  "fixtures_v1",
);

/**
 * Two leagues in the directory, the newer naming this capture's table and the older an
 * earlier one; the calendar; and the forwarder's bundle answer.
 */
function site({
  bundle = () => marked(BUNDLE),
  lines = [line(352490, 6, OLDER, OLDER_BYTES), line(755941, 7, CAPTURE, TABLE_BYTES)],
  calendar = OPEN_WEEK,
  standings = STANDINGS_EXAMPLES.first_page,
}: {
  bundle?: () => Response;
  lines?: unknown[];
  calendar?: unknown;
  standings?: unknown;
} = {}) {
  return stubFetchByUrl([
    [
      "/data/leagues.json",
      () =>
        jsonResponse(
          envelope({ leagues: lines }, "league_directory_v1") as unknown as Record<string, unknown>,
        ),
    ],
    [
      /\/data\/device\/[^/]+\/device-plan\.json\?v=/,
      (url) => new Response(url.includes(CAPTURE) ? TABLE_BYTES : OLDER_BYTES),
    ],
    ["/data/fixtures.json", () => jsonResponse(calendar)],
    [`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`, bundle],
    [/\/api\/v1\/fpl\/standings\/314\?page=1$/, () => marked(standings)],
  ]);
}

/** The real solver's answer for the fixture member, in process; it keeps what it was asked. */
class CannedSolver implements DeviceSolver {
  onmessage: ((event: MessageEvent<DevicePlanReply>) => void) | null = null;
  readonly asked: DevicePlanRequest[] = [];
  terminate(): void {}
  postMessage(request: DevicePlanRequest): void {
    this.asked.push(request);
    const reference = member.reference;
    const reply: DevicePlanReply = {
      id: request.id,
      kind: "answer",
      answer: {
        objective_scaled: 0,
        chip: null,
        objective: reference.objective_value,
        squad: reference.squad,
        starting_xi: reference.starting_xi,
        captain: reference.captain,
        vice_captain: reference.vice_captain,
        bench: reference.bench,
        transfers_in: reference.transfers_in,
        transfers_out: reference.transfers_out,
        transfer_hit_points: reference.transfer_hit_points,
        expected_own_points: reference.expected_own_points,
        hold_points: reference.hold_points,
        moves: reference.moves,
        expected_gain_vs_hold: reference.expected_gain_vs_hold,
        seconds: 0.42,
      },
    };
    queueMicrotask(() => {
      this.onmessage?.({
        data: { id: request.id, kind: "ready" },
      } as MessageEvent<DevicePlanReply>);
      this.onmessage?.({ data: reply } as MessageEvent<DevicePlanReply>);
    });
  }
}

function open(language: Language, address: string, dependencies: ForwardedMemberDependencies = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page = (children: ReactNode) => (
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>{children}</LanguageProvider>
    </QueryClientProvider>
  );
  return render(
    page(
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route
            path="/entry/:entryId"
            element={<ForwardedMemberPage dependencies={dependencies} />}
          />
          <Route
            path="/league/:leagueId/members/:entryId/:tool?"
            element={
              <ForwardedLeagueContext.Provider
                value={{ leagueId: 314, leagueName: "Synthetic League" }}
              >
                <ForwardedMemberPage dependencies={dependencies} />
              </ForwardedLeagueContext.Provider>
            }
          />
        </Routes>
      </MemoryRouter>,
    ),
  );
}

describe.each(["tr", "en"] as const)("a team through the forwarder in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;
  const words = MESSAGES[language].forwarded;

  it("queues only after a server click and renders its completed plan", async () => {
    site();
    const solver = new CannedSolver();
    const answer = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    Object.assign(answer.payload, {
      league_id: 314,
      season: TABLE.season,
      gameweek: TABLE.gameweek,
      source_snapshot_id: CAPTURE,
    });
    const requestAdvice = vi.fn<AdviceClient["requestAdvice"]>().mockResolvedValue({
      kind: "job",
      jobId: "public-one",
      status: "queued",
    });
    const server: AdviceClient = {
      requestAdvice,
      readJob: vi.fn().mockResolvedValue({ jobId: "public-one", status: "completed" }),
      readAdvice: vi
        .fn()
        .mockResolvedValue({ kind: "advice", envelope: answer, source: "api-cache" }),
      readPublished: vi.fn().mockResolvedValue({ kind: "not-computed" }),
    };
    open(language, `/league/314/members/${ENTRY}`, {
      server,
      device: { createSolver: () => solver },
    });
    const button = await screen.findByRole("button", { name: COMPUTE_COPY[language].serverButton });
    expect(requestAdvice).not.toHaveBeenCalled();
    expect(solver.asked).toHaveLength(0);
    await userEvent.setup().click(button);
    expect(await screen.findByText(copy.computeQueued)).toBeVisible();
    expect(screen.getByRole("button", { name: copy.deviceButton })).toBeDisabled();
    expect(screen.queryByText(COMPUTE_COPY[language].leaveOpen)).toBeNull();
    expect(await screen.findByText(copy.computeDone, {}, { timeout: 5000 })).toBeVisible();
    expect(requestAdvice).toHaveBeenCalledTimes(1);
    expect(requestAdvice.mock.calls[0]![0]).toMatchObject({
      publicEntry: true,
      leagueId: 314,
      entryId: ENTRY,
    });
    expect(solver.asked).toHaveLength(0);
    expect(server.readPublished).not.toHaveBeenCalled();
  });

  it("refuses a server result from another capture", async () => {
    site();
    const answer = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    Object.assign(answer.payload, {
      league_id: 0,
      season: TABLE.season,
      gameweek: TABLE.gameweek,
      source_snapshot_id: OLDER,
    });
    const server: AdviceClient = {
      requestAdvice: async (): Promise<AdviceRequestResult> => ({
        kind: "advice",
        envelope: answer,
        source: "api-cache",
      }),
      readJob: vi.fn(),
      readAdvice: vi.fn(),
      readPublished: vi.fn(),
    };
    open(language, `/entry/${ENTRY}`, { server });
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: COMPUTE_COPY[language].serverButton }));
    expect(
      await screen.findByText(COMPUTE_COPY[language].failures.ANSWER_OTHER_CAPTURE),
    ).toBeVisible();
    expect(screen.queryByText(copy.computeDone)).toBeNull();
  });

  it("opens without computing and runs on the device only when asked", async () => {
    const fetcher = site();
    const solver = new CannedSolver();
    open(language, `/entry/${ENTRY}`, { device: { createSolver: () => solver } });
    expect(await screen.findByRole("heading", { name: "Synthetic XI", level: 1 })).toBeVisible();
    expect(solver.asked).toHaveLength(0);
    await userEvent.setup().click(screen.getByRole("button", { name: copy.deviceButton }));
    await waitFor(() =>
      expect(document.querySelector('[data-device-state="done"]')).not.toBeNull(),
    );
    // The transfers the server's reference names, by the names the table gives them.
    const names = new Map(TABLE.players.map((player) => [player.id, player.name]));
    for (const move of member.reference.moves) {
      expect(screen.getAllByText(names.get(move.in!)!).length).toBeGreaterThan(0);
    }
    // The device was given the block the run publishes for this member, and the table.
    expect(solver.asked).toHaveLength(1);
    expect(solver.asked[0]!.entry).toEqual({ ...member.entry, held: FIFTEEN });
    expect(solver.asked[0]!.document.source_snapshot_id).toBe(CAPTURE);
    const urls = fetcher.mock.calls.map(([url]) => url);
    expect(urls).toContain(`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`);
    expect(urls.some((url) => url.includes(OLDER))).toBe(false);
    // An entry on its own names no league.
    expect(screen.queryByRole("link", { name: words.backToLeague })).toBeNull();
    // Nothing on the page is a chance or a caveat.
    const page = document.body.textContent ?? "";
    expect(page).not.toMatch(AS_A_CHANCE);
    expect(page).not.toMatch(AS_A_CAVEAT);
  });

  it("opens a member of a forwarded league under it, named as its table names them", async () => {
    const first = STANDINGS_EXAMPLES.first_page;
    site({
      standings: {
        ...first,
        results: [
          {
            ...first.results[0]!,
            entry: ENTRY,
            entry_name: "Table Team",
            player_name: "Table Manager",
          },
          ...first.results.slice(1),
        ],
      },
    });
    const solver = new CannedSolver();
    open(language, `/league/314/members/${ENTRY}`, { device: { createSolver: () => solver } });
    expect(await screen.findByRole("heading", { name: "Table Team", level: 1 })).toBeVisible();
    expect(screen.getByText("Table Manager")).toBeVisible();
    expect(screen.getByRole("link", { name: words.backToLeague })).toHaveAttribute(
      "href",
      "/league/314",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: copy.deviceButton }));
    await waitFor(() =>
      expect(document.querySelector('[data-device-state="done"]')).not.toBeNull(),
    );
  });

  it("says the plan cannot be computed when the bundle holds another week's picks", async () => {
    const stale: FplEntryBundle = { ...BUNDLE, picks: BUNDLE.picks.slice(0, 1) };
    site({ bundle: () => marked(stale) });
    const create = vi.fn(() => new CannedSolver());
    open(language, `/entry/${ENTRY}`, { device: { createSolver: create } });
    expect(await screen.findByText(words.planNotComputable)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Synthetic XI", level: 1 })).toBeVisible();
    // Nothing else: no plan, no squad, no device run.
    expect(screen.queryByRole("heading", { name: copy.decisionTitle })).toBeNull();
    expect(screen.queryByText(copy.startingXiLabel)).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  it("says the plan cannot be computed when the directory names no table", async () => {
    site({ lines: [{ ...line(352490, 7, CAPTURE, TABLE_BYTES), device_plan: undefined }] });
    open(language, `/entry/${ENTRY}`);
    expect(await screen.findByText(words.planNotComputable)).toBeInTheDocument();
  });

  it("names an id FPL has no team for", async () => {
    site({ bundle: () => marked({ error: "entry_not_found" }, 404) });
    open(language, `/entry/${ENTRY}`);
    expect(await screen.findByText(words.teamNotFound(ENTRY))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: words.retry })).toBeNull();
  });

  it("says the team cannot be opened now with the forwarder down, and reads it again", async () => {
    let down = true;
    site({
      bundle: () => (down ? new Response("<!doctype html>", { status: 200 }) : marked(BUNDLE)),
    });
    const solver = new CannedSolver();
    open(language, `/entry/${ENTRY}`, { device: { createSolver: () => solver } });
    expect(await screen.findByText(words.teamUnavailable)).toBeInTheDocument();
    down = false;
    await userEvent.setup().click(screen.getByRole("button", { name: words.retry }));
    await userEvent.setup().click(await screen.findByRole("button", { name: copy.deviceButton }));
    await waitFor(() =>
      expect(document.querySelector('[data-device-state="done"]')).not.toBeNull(),
    );
  });

  it("refuses an address that is not a team number", async () => {
    site();
    open(language, "/entry/12ab");
    expect(await screen.findByText(copy.invalidEntry)).toBeInTheDocument();
  });

  it("asks the forwarder for the bundle once when the live card reads it too", async () => {
    const BUNDLE_URL = `/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`;
    const fetcher = site({
      bundle: () => marked({ ...BUNDLE, current_week: exampleMember(ENTRY, TABLE.gameweek) }),
      calendar: envelope(
        exampleCalendar({
          season: TABLE.season,
          gameweek: TABLE.gameweek,
          deadline: "2020-01-01T00:00:00Z",
        }),
        "fixtures_v1",
      ),
    });
    open(language, `/entry/${ENTRY}`);
    expect(await screen.findByText(COMPUTE_COPY[language].deadlinePassedTitle)).toBeInTheDocument();
    // The live card went on to the week's live points, with the page's own bundle.
    await waitFor(() =>
      expect(fetcher.mock.calls.map(([url]) => url)).toContain(
        `/api/v1/fpl/live/${TABLE.gameweek}`,
      ),
    );
    expect(fetcher.mock.calls.filter(([url]) => url === BUNDLE_URL)).toHaveLength(1);
  });

  it("shows the live score once the deadline has passed, and solves nothing", async () => {
    const deadline = "2020-01-01T00:00:00Z";
    site({
      calendar: envelope(
        exampleCalendar({ season: TABLE.season, gameweek: TABLE.gameweek, deadline }),
        "fixtures_v1",
      ),
    });
    const create = vi.fn(() => new CannedSolver());
    const live = exampleBundle(ENTRY, TABLE.gameweek, exampleMember(ENTRY, TABLE.gameweek));
    open(language, `/entry/${ENTRY}`, {
      device: { createSolver: create },
      live: {
        forwarder: {
          entryBundle: async () => ({ ok: true, document: live, copy: "miss" }) as const,
          liveWeek: async () =>
            ({
              ok: true,
              document: forwardedLive("in_progress", TABLE.gameweek),
              copy: "miss",
            }) as const,
        },
        loadTable: async () =>
          envelope(
            exampleTable({ season: TABLE.season, gameweek: TABLE.gameweek, capture: CAPTURE }),
          ) as never,
      },
    });
    expect(await screen.findByText(COMPUTE_COPY[language].deadlinePassedTitle)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector("[data-member-live-score]")).not.toBeNull());
    expect(document.querySelectorAll('#kadro [data-points-kind="actual"]')).toHaveLength(15);
    expect(document.querySelectorAll('#kadro [data-points-kind="expected"]')).toHaveLength(0);
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: copy.decisionTitle })).toBeVisible();
    expect(screen.getByRole("heading", { name: copy.memberSquad })).toBeVisible();
    expect(screen.getByRole("button", { name: copy.deviceButton })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: COMPUTE_COPY[language].serverButton }),
    ).toBeDisabled();
  });

  it.each([`/entry/${ENTRY}`, `/league/314/members/${ENTRY}`])(
    "keeps the current squad and disabled controls at %s when live points are unavailable",
    async (address) => {
      const incoming = TABLE.players.find(
        (player) => player.position === "GK" && !FIFTEEN.includes(player.id),
      )!;
      site({
        bundle: () =>
          marked({
            ...BUNDLE,
            current_week: {
              ...exampleMember(ENTRY, TABLE.gameweek),
              pick_order: [incoming.id, ...FIFTEEN.slice(1)],
              captain: 139,
              vice: 132,
            },
          }),
        calendar: envelope(
          exampleCalendar({
            season: TABLE.season,
            gameweek: TABLE.gameweek,
            deadline: "2020-01-01T00:00:00Z",
          }),
          "fixtures_v1",
        ),
      });
      const create = vi.fn(() => new CannedSolver());
      const server: AdviceClient = {
        requestAdvice: vi.fn(),
        readJob: vi.fn(),
        readAdvice: vi.fn(),
        readPublished: vi.fn(),
      };
      open(language, address, {
        server,
        device: { createSolver: create },
        live: {
          forwarder: {
            entryBundle: async () => ({ ok: false, reason: "upstream_unavailable" }) as const,
            liveWeek: vi.fn(),
          },
        },
      });
      expect(await screen.findByRole("heading", { name: copy.memberSquad })).toBeVisible();
      expect(document.querySelectorAll("#kadro [data-player-motion]")).toHaveLength(15);
      expect(document.querySelectorAll("#kadro [data-player-points]")).toHaveLength(0);
      expect(document.querySelector(`#kadro [data-player-motion="${incoming.id}"]`)).not.toBeNull();
      expect(document.querySelector(`#kadro [data-player-motion="${FIFTEEN[0]}"]`)).toBeNull();
      const deviceButton = screen.getByRole("button", { name: copy.deviceButton });
      const serverButton = screen.getByRole("button", {
        name: COMPUTE_COPY[language].serverButton,
      });
      expect(deviceButton).toBeDisabled();
      expect(serverButton).toBeDisabled();
      await userEvent.setup().click(deviceButton);
      await userEvent.setup().click(serverButton);
      expect(create).not.toHaveBeenCalled();
      expect(server.requestAdvice).not.toHaveBeenCalled();
      expect(document.querySelector("[data-member-live-score]")).toBeNull();
    },
  );
});
