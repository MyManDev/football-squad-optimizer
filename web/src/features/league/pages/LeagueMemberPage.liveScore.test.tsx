/**
 * The member's live week on their page (#1008): read once the week's deadline has passed,
 * shown beside the notice that says so, and never on the open week's page or a tool page.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  exampleBundle,
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
} from "../../../fixtures/forwarder";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { withLeague } from "../../../testSupport/league";
import type { AdviceClient } from "../advice/adviceClient";
import type { ForwarderClient } from "../forwarder/client";
import type { MemberLiveDependencies } from "../live/useMemberLiveScore";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";

afterEach(cleanup);

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const { season, gameweek, source_snapshot_id: capture } = SQUAD.payload;
const DEADLINE = "2026-08-21T17:30:00Z";
const CALENDAR = exampleCalendar({ season, gameweek, deadline: DEADLINE });

const QUIET: AdviceClient = {
  readAdvice: async () => ({ kind: "not-computed" }),
  readPublished: async () => ({ kind: "not-computed" }),
  requestAdvice: () => Promise.reject(new Error("nothing is requested")),
  readJob: () => Promise.reject(new Error("nothing is polled")),
};

function dependencies() {
  const member = exampleMember(ENTRY, gameweek);
  const forwarder = {
    entryBundle: vi.fn<ForwarderClient["entryBundle"]>(async () => ({
      ok: true,
      document: exampleBundle(ENTRY, gameweek, member),
      copy: "miss",
    })),
    liveWeek: vi.fn<ForwarderClient["liveWeek"]>(async () => ({
      ok: true,
      document: forwardedLive("in_progress", gameweek),
      copy: "miss",
    })),
  };
  const loadTable = vi.fn<NonNullable<MemberLiveDependencies["loadTable"]>>(async () => ({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: DEADLINE,
    source_kind: "live",
    payload: exampleTable({ season, gameweek, capture: capture! }),
  }));
  return { forwarder, loadTable };
}

function renderPage(props: Partial<LeagueMemberViewProps>) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
        {withLeague(
          <LeagueMemberView
            index={mockEntryAdviceIndex(ENTRY).payload}
            squad={SQUAD}
            advice={mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)}
            client={QUIET}
            {...props}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the member's live week on their page", () => {
  it("stands beside the notice that the week's deadline has passed", async () => {
    const live = dependencies();
    renderPage({ deadlinePassed: DEADLINE, fixtures: CALENDAR, liveDependencies: live });
    const title = await screen.findByRole("heading", { name: `${gameweek}. hafta puanın` });
    const notice = screen.getByTestId("deadline-passed");
    const card = title.closest("[data-member-live-score]")!;
    expect(notice.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(notice.nextElementSibling).toBe(card);
    expect(live.forwarder.entryBundle).toHaveBeenCalledWith(ENTRY, gameweek, expect.anything());
  });

  it("is not read while the week is open", async () => {
    const live = dependencies();
    renderPage({ deadlinePassed: null, fixtures: CALENDAR, liveDependencies: live });
    await screen.findByRole("heading", { level: 1 });
    expect(live.forwarder.entryBundle).not.toHaveBeenCalled();
    expect(screen.queryByText(`${gameweek}. hafta puanın`)).toBeNull();
    expect(document.querySelectorAll('#kadro [data-points-kind="expected"]')).toHaveLength(15);
  });

  it("refreshes the total and all fifteen's raw points from the same live response", async () => {
    const live = dependencies();
    const playing = forwardedLive("in_progress", gameweek);
    const finished = forwardedLive("finished", gameweek);
    finished.source_time = new Date(Date.parse(playing.source_time) + 60_000).toISOString();
    live.forwarder.liveWeek
      .mockResolvedValueOnce({ ok: true, document: playing, copy: "miss" })
      .mockResolvedValueOnce({ ok: true, document: finished, copy: "miss" });
    const { container } = renderPage({
      deadlinePassed: DEADLINE,
      fixtures: CALENDAR,
      liveDependencies: live,
    });
    const table = exampleTable({ season, gameweek, capture: capture! });
    const checkPoints = async (week: typeof playing) => {
      for (const element of week.elements) {
        const player = table.players.find((row) => row.element_id === element.element_id);
        if (!player) continue;
        await waitFor(() =>
          expect(
            container.querySelector(
              `#kadro [data-player-motion="${player.id}"] [data-player-points]`,
            ),
          ).toHaveAttribute("data-player-points", String(element.points)),
        );
      }
    };
    await screen.findByRole("heading", { name: `${gameweek}. hafta puanın` });
    await checkPoints(playing);
    expect(container.querySelectorAll('#kadro [data-points-kind="actual"]')).toHaveLength(15);
    fireEvent.click(screen.getByRole("button", { name: "Yenile" }));
    await screen.findByText("Bonus eklendi");
    await checkPoints(finished);
    expect(live.forwarder.entryBundle).toHaveBeenCalledTimes(1);
    expect(live.forwarder.liveWeek).toHaveBeenCalledTimes(2);
  });

  it("keeps the team without forecast or historical scores when live points cannot be read", async () => {
    const live = dependencies();
    live.forwarder.liveWeek.mockResolvedValue({ ok: false, reason: "upstream_unavailable" });
    const { container } = renderPage({
      deadlinePassed: DEADLINE,
      fixtures: CALENDAR,
      liveDependencies: live,
    });
    await waitFor(() => expect(live.forwarder.liveWeek).toHaveBeenCalledOnce());
    expect(container.querySelectorAll("#kadro [data-player-motion]")).toHaveLength(15);
    expect(container.querySelectorAll("#kadro [data-player-points]")).toHaveLength(0);
  });

  it("uses actual points on the current-squad list too", async () => {
    const live = dependencies();
    const { container } = renderPage({
      deadlinePassed: DEADLINE,
      fixtures: CALENDAR,
      liveDependencies: live,
      tool: "current-squad",
    });
    await waitFor(() =>
      expect(container.querySelectorAll('[data-points-kind="actual"]')).toHaveLength(15),
    );
    expect(container.querySelectorAll('[data-points-kind="expected"]')).toHaveLength(0);
  });

  it("is not read without the calendar, which names each club's id", async () => {
    const live = dependencies();
    renderPage({ deadlinePassed: DEADLINE, fixtures: null, liveDependencies: live });
    await screen.findByTestId("deadline-passed");
    expect(live.forwarder.entryBundle).not.toHaveBeenCalled();
  });

  it("is not on a tool page", async () => {
    const live = dependencies();
    renderPage({
      deadlinePassed: DEADLINE,
      fixtures: CALENDAR,
      liveDependencies: live,
      tool: "chips",
    });
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(live.forwarder.entryBundle).not.toHaveBeenCalled());
    expect(screen.queryByText(`${gameweek}. hafta puanın`)).toBeNull();
  });
});
