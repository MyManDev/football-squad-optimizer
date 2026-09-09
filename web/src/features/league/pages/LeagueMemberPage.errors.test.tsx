import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { points } from "../../../lib/format";
import * as data from "../data";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";
import { LeagueMembersPage, LeagueMembersView } from "./LeagueMembersPage";

const ENTRY = 35249001;
const clients: QueryClient[] = [];

beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(data, "loadLeagueMembers").mockResolvedValue(mockLeagueMembersEnvelope);
  vi.spyOn(data, "loadEntrySquad").mockImplementation(async (id) => mockEntrySquadEnvelopes[id]!);
  vi.spyOn(data, "loadEntryAdviceIndex").mockImplementation(async (id) => mockEntryAdviceIndex(id));
  vi.spyOn(data, "loadEntryAdvice").mockImplementation(async (id, mode, window, rival) =>
    mockEntryAdviceEnvelope(id, mode, window, rival),
  );
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function open(language: Language, list = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[list ? "/league/members" : `/league/members/${ENTRY}`]}>
          <Routes>
            <Route path="/league/members" element={<LeagueMembersPage />} />
            <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

function showAdvice(
  language: Language,
  advice: LeagueViewEnvelope<EntryAdvice>,
  index = mockEntryAdviceIndex(ENTRY).payload,
) {
  const search = new URLSearchParams({
    mode: advice.payload.mode,
    window: String(advice.payload.window),
  });
  if (advice.payload.rival_entry_id != null)
    search.set("rival", String(advice.payload.rival_entry_id));
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${search}`]}>
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[ENTRY]!}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={index}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("honest publication states in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;

  it.each(["missing", "unreadable"] as const)("distinguishes a %s member list", async (kind) => {
    vi.mocked(data.loadLeagueMembers).mockRejectedValue(
      kind === "missing"
        ? new data.LeagueDataMissing("members.json")
        : new data.LeagueDataError("503"),
    );
    open(language, true);
    expect(
      await screen.findByText(kind === "missing" ? copy.notAvailable : copy.membersUnreadable),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(kind === "missing" ? copy.membersUnreadable : copy.notAvailable),
    ).not.toBeInTheDocument();
  });

  it.each(["missing", "unreadable"] as const)(
    "shows the %s member error even while its index is pending",
    async (kind) => {
      vi.mocked(data.loadEntrySquad).mockRejectedValue(
        kind === "missing"
          ? new data.LeagueDataMissing(`entries/${ENTRY}.json`)
          : new data.LeagueDataError("bad JSON"),
      );
      vi.mocked(data.loadEntryAdviceIndex).mockReturnValue(new Promise(() => {}));
      open(language);
      expect(
        await screen.findByText(kind === "missing" ? copy.entryNotAvailable : copy.entryUnreadable),
      ).toBeInTheDocument();
      expect(screen.getByRole("link", { name: copy.backToMembers })).toHaveAttribute(
        "href",
        "/league/members",
      );
      expect(
        screen.queryByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
      ).not.toBeInTheDocument();
      expect(data.loadEntryAdvice).not.toHaveBeenCalled();
    },
  );

  it("keeps a loaded squad visible while the index remains pending", async () => {
    vi.mocked(data.loadEntryAdviceIndex).mockReturnValue(new Promise(() => {}));
    open(language);
    expect(
      await screen.findByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.loadingAdvice)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.computeButton })).toBeDisabled();
    expect(data.loadEntryAdvice).not.toHaveBeenCalled();
  });

  it.each(["missing", "unreadable"] as const)(
    "distinguishes a listed advice file that is %s",
    async (kind) => {
      vi.mocked(data.loadEntryAdvice).mockRejectedValue(
        kind === "missing"
          ? new data.LeagueDataMissing("listed-plan.json")
          : new data.LeagueDataError("503"),
      );
      open(language);
      expect(
        await screen.findByText(
          kind === "missing"
            ? copy.publicationStates["published-missing"].title
            : copy.adviceUnreadable,
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(copy.publicationStates["declared-unavailable"].title),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(copy.adviceNotComputed)).not.toBeInTheDocument();
    },
  );

  it("keeps the squad visible while advice is pending and then displays its response", async () => {
    let finish!: (value: LeagueViewEnvelope<EntryAdvice>) => void;
    vi.mocked(data.loadEntryAdvice).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    open(language);
    expect(
      await screen.findByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
    ).toBeInTheDocument();
    expect(await screen.findByText(copy.loadingAdvice)).toBeInTheDocument();
    await act(async () => finish(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)));
    expect(await screen.findByText(copy.lineupTitle)).toBeInTheDocument();
  });

  it("retries the same published advice after a read error while retaining the squad", async () => {
    let finish!: (value: LeagueViewEnvelope<EntryAdvice>) => void;
    vi.mocked(data.loadEntryAdvice)
      .mockRejectedValueOnce(new data.LeagueDataError("503"))
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
    open(language);
    expect(await screen.findByText(copy.adviceUnreadable)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: copy.retryPublishedRead }));
    expect(
      screen.getByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
    ).toBeInTheDocument();
    expect(data.loadEntryAdvice).toHaveBeenCalledTimes(2);
    expect(data.loadEntryAdvice).toHaveBeenNthCalledWith(1, ENTRY, "saf-puan", 1, null);
    expect(data.loadEntryAdvice).toHaveBeenNthCalledWith(2, ENTRY, "saf-puan", 1, null);
    await act(async () => finish(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)));
    expect(await screen.findByText(copy.lineupTitle)).toBeInTheDocument();
    expect(screen.queryByText(copy.adviceUnreadable)).not.toBeInTheDocument();
  });

  it.each(["gameweek", "source_snapshot_id"] as const)(
    "labels rejected %s context honestly",
    (field) => {
      const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
      if (field === "gameweek") advice.payload.gameweek += 1;
      else advice.payload.source_snapshot_id = "a-different-capture";
      showAdvice(language, advice);
      expect(
        screen.getByText(copy.publicationStates["context-mismatch"].title),
      ).toBeInTheDocument();
      expect(screen.queryByText(copy.lineupTitle)).not.toBeInTheDocument();
      expect(screen.queryByText(copy.adviceNotComputed)).not.toBeInTheDocument();
    },
  );

  it("keeps absent FEASIBLE gaps unknown", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.solver_status = "FEASIBLE";
    advice.payload.control_solver_status = "FEASIBLE";
    advice.payload.optimality_gap = null;
    delete advice.payload.control_optimality_gap;
    showAdvice(language, advice);
    expect(screen.getByText(copy.unprovenPlanGapUnknown)).toBeInTheDocument();
    expect(screen.getByText(copy.controlGapUnknown)).toBeInTheDocument();
  });

  it.each(["moves", "generated_at_utc"] as const)(
    "keeps malformed advice %s distinct from different context",
    (field) => {
      const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
      if (field === "moves") advice.payload.moves = null as unknown as EntryAdvice["moves"];
      else delete (advice as { generated_at_utc?: string }).generated_at_utc;
      showAdvice(language, advice);
      expect(screen.getByText(copy.adviceUnreadable)).toBeInTheDocument();
      expect(
        screen.queryByText(copy.publicationStates["context-mismatch"].title),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(copy.adviceNotComputed)).not.toBeInTheDocument();
    },
  );

  it("preserves measured zero gaps", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.solver_status = "FEASIBLE";
    advice.payload.control_solver_status = "FEASIBLE";
    advice.payload.optimality_gap = 0;
    advice.payload.control_optimality_gap = 0;
    showAdvice(language, advice);
    const zero = points(0, 1, language === "tr" ? "tr-TR" : "en-GB");
    expect(screen.getByText(copy.unprovenPlanBody(zero))).toBeInTheDocument();
    expect(screen.getByText(copy.controlUnprovenBody(zero))).toBeInTheDocument();
    expect(screen.queryByText(copy.unprovenPlanGapUnknown)).not.toBeInTheDocument();
  });

  it("does not invent an applied overlap bound or alternative hit points", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "ortak-koru", 1));
    advice.payload.plan_kind = "within_free_transfers";
    advice.payload.transfer_cap = 1;
    advice.payload.overlap_target = 8;
    delete advice.payload.overlap_applied;
    advice.payload.alternative_plan = {
      kind: "with_hits",
      overlap_applied: 8,
      transfer_hit_points: null,
      expected_points_cost: 2,
      expected_points_cost_ceiling: 2,
    };
    showAdvice(language, advice);
    expect(
      screen.getByText(copy.planWithinFreeUnknown(1, 8), { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.hitPointsNotPublished, { exact: false })).toBeInTheDocument();
  });

  it("does not equate incomplete source data with a withheld plan", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.moves = [];
    advice.payload.solver_status = "OPTIMAL";
    advice.payload.data_quality = "partial";
    showAdvice(language, advice);
    expect(screen.getByText(copy.noMove)).toBeInTheDocument();
    expect(screen.queryByText(copy.noAdviceMissingData)).not.toBeInTheDocument();
  });

  it("preserves a zero overlap bound, measured hit points and plan cost", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "ortak-koru", 1));
    advice.payload.solver_status = "OPTIMAL";
    advice.payload.control_solver_status = "OPTIMAL";
    advice.payload.plan_kind = "within_free_transfers";
    advice.payload.transfer_cap = 1;
    advice.payload.overlap_target = 8;
    advice.payload.overlap_applied = 0;
    advice.payload.expected_points_cost = 0;
    advice.payload.expected_points_cost_ceiling = 0;
    advice.payload.alternative_plan = {
      kind: "with_hits",
      overlap_applied: 8,
      transfer_hit_points: 0,
      expected_points_cost: 2,
      expected_points_cost_ceiling: 2,
    };
    showAdvice(language, advice);
    const locale = language === "tr" ? "tr-TR" : "en-GB";
    expect(screen.getByText(copy.planWithinFree(1, 8, 0), { exact: false })).toBeInTheDocument();
    expect(
      screen.getByText(copy.alternativeWithHits(8, points(0, 0, locale), points(2, 1, locale)), {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.planCost(points(0, 1, locale)))).toBeInTheDocument();
    expect(
      screen.queryByText(copy.hitPointsNotPublished, { exact: false }),
    ).not.toBeInTheDocument();
  });

  it("does not invent a zero-transfer plan from an empty record", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.moves = [];
    advice.payload.data_quality = "empty";
    advice.payload.starting_xi = null;
    advice.payload.bench = null;
    advice.payload.solver_status = null;
    showAdvice(language, advice);
    expect(screen.getByText(copy.noPlanInRecord)).toBeInTheDocument();
    expect(screen.queryByText(copy.noMove)).not.toBeInTheDocument();
  });

  it.each(["__proto__", "toString", "Raw producer diagnostic: probability 97% chance"])(
    "keeps unrecognized producer reason %s out of product copy",
    (reason) => {
      const advice = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
      const index = structuredClone(mockEntryAdviceIndex(ENTRY).payload);
      index.unavailable.push({ strategy: "saf-puan", rival_entry_id: null, window: 1, reason });
      const page = showAdvice(language, advice, index);
      expect(
        screen.getByText(copy.publicationStates["declared-unavailable"].title),
      ).toBeInTheDocument();
      expect(screen.getByText(copy.publicationReasonUnknown)).toBeInTheDocument();
      expect(page.container.textContent).not.toContain(reason);
    },
  );

  it("does not render string-valued costs as measured numbers", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "ortak-koru", 1));
    advice.payload.solver_status = "OPTIMAL";
    advice.payload.control_solver_status = "OPTIMAL";
    advice.payload.expected_points_cost = "7" as unknown as number;
    delete advice.payload.expected_points_cost_ceiling;
    showAdvice(language, advice);
    const value = points(7, 1, language === "tr" ? "tr-TR" : "en-GB");
    expect(screen.queryByText(copy.planCost(value))).not.toBeInTheDocument();
  });

  it.each([
    { movement: "up", places: null, expected: "unknown" },
    { movement: "down", places: undefined, expected: "unknown" },
    { movement: "up", places: Number.POSITIVE_INFINITY, expected: "unknown" },
    { movement: "same", places: null, expected: "—" },
    { movement: "up", places: 0, expected: "↑ 0" },
    { movement: "down", places: 2, expected: "↓ 2" },
    { movement: "new", places: null, expected: "new" },
  ] as const)(
    "preserves missing versus measured movement: $movement/$places",
    ({ movement, places, expected }) => {
      const envelope = structuredClone(mockLeagueMembersEnvelope);
      const member = envelope.payload.members.find((entry) => entry.member_kind === "human")!;
      member.movement = movement;
      if (places === undefined)
        delete (member as { movement_places?: number | null }).movement_places;
      else member.movement_places = places;
      render(
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter>
            <LeagueMembersView envelope={envelope} />
          </MemoryRouter>
        </LanguageProvider>,
      );
      const row = screen.getByRole("link", { name: member.manager_name! }).closest("tr")!;
      const movementCell = within(row).getAllByRole("cell").at(-1)!;
      expect(movementCell).toHaveTextContent(
        expected === "unknown" ? copy.unknown : expected === "new" ? copy.newMember : expected,
      );
    },
  );
});
