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
import { COMPUTE_COPY } from "../advice/computeCopy";
import { EXAMPLE_LEAGUE, stubTree, withLeague } from "../../../testSupport/league";
import { memberAddress, membersAddress } from "../../../lib/leagueAddresses";
import * as data from "../data";
import type { LeagueTree } from "../data";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberPage, LeagueMemberView } from "./LeagueMemberPage";
import { LeagueMembersPage, LeagueMembersView } from "./LeagueMembersPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";

const ENTRY = 35249001;
const LEAGUE = EXAMPLE_LEAGUE.leagueId;
const clients: QueryClient[] = [];
/** The example tree's reads, replaced for the page under test. */
const reads = {
  members: vi.fn<LeagueTree["members"]>(),
  entrySquad: vi.fn<LeagueTree["entrySquad"]>(),
  entryAdviceIndex: vi.fn<LeagueTree["entryAdviceIndex"]>(),
  entryAdvice: vi.fn<LeagueTree["entryAdvice"]>(),
};
// The proof caveats the member page used to print for a FEASIBLE plan or control, by literal:
// none of them may come back under any key.
const PROOF_CAVEATS: Record<Language, readonly RegExp[]> = {
  tr: [
    /Kanıt tamamlanamadı/,
    /kanıtı tamamlayamadı/,
    /en iyi olduğu kanıtlanamadı/,
    /en iyi diye kanıtlanamadı/,
    /fiyat belirtilmiyor/,
    /Karar vermeden önce gösterilen on biri/,
  ],
  en: [
    /Proof incomplete/,
    /could not finish the proof/,
    /proof for this plan is incomplete/,
    /was not proven optimal/,
    /no price is stated/,
    /Review the shown lineup and transfers before deciding/,
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  for (const read of Object.values(reads)) read.mockReset();
  reads.members.mockResolvedValue(mockLeagueMembersEnvelope);
  reads.entrySquad.mockImplementation(async (id) => mockEntrySquadEnvelopes[id]!);
  reads.entryAdviceIndex.mockImplementation(async (id) => mockEntryAdviceIndex(id));
  reads.entryAdvice.mockImplementation(async (id, mode, window, rival) =>
    mockEntryAdviceEnvelope(id, mode, window, rival),
  );
  stubTree(reads);
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
        <MemoryRouter
          initialEntries={[list ? membersAddress(LEAGUE) : memberAddress(LEAGUE, ENTRY)]}
        >
          {withLeague(
            <Routes>
              <Route path="/league/:leagueId/members" element={<LeagueMembersPage />} />
              <Route path="/league/:leagueId/members/:entryId" element={<LeagueMemberPage />} />
            </Routes>,
          )}
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
      <MemoryRouter initialEntries={[memberAddress(LEAGUE, ENTRY, `?${search}`)]}>
        {withLeague(
          <LeagueMemberView
            squad={mockEntrySquadEnvelopes[ENTRY]!}
            advice={advice}
            members={mockLeagueMembersEnvelope.payload.members}
            index={index}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe.each(["tr", "en"] as const)("honest publication states in %s", (language) => {
  const copy = MESSAGES[language].leagueMembers;

  it.each([
    "published",
    "not-listed",
    "declared-unavailable",
    "index-missing",
    "index-error",
    "invalid-index",
    "loading",
    "published-missing",
    "unavailable",
    "rejected-context",
    "rejected-unreadable",
    "different-selection",
  ] as const)("keeps the unreachable-service notice honest for %s", (kind) => {
    const props: LeagueMemberViewProps = {
      squad: mockEntrySquadEnvelopes[ENTRY]!,
      advice: structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)),
      index: structuredClone(mockEntryAdviceIndex(ENTRY).payload),
      members: mockLeagueMembersEnvelope.payload.members,
      computeService: "unreachable",
    };
    if (kind === "index-missing") {
      props.index = null;
      props.adviceIssue = kind;
    }
    if (kind === "index-error") props.adviceIssue = kind;
    if (kind === "invalid-index") props.index!.gameweek += 1;
    if (kind === "not-listed") props.index!.windows = { "saf-puan": [1] };
    if (kind === "loading") props.adviceLoading = true;
    if (kind === "published-missing" || kind === "unavailable") {
      props.advice = null;
      props.adviceIssue = kind;
    }
    if (kind === "rejected-context") props.advice!.payload.source_snapshot_id = "different-capture";
    if (kind === "rejected-unreadable")
      props.advice!.payload.moves = null as unknown as EntryAdvice["moves"];
    if (kind === "declared-unavailable")
      props.index!.unavailable.push({
        strategy: "saf-puan",
        window: 1,
        rival_entry_id: null,
        reason: "not-computed",
      });
    const query =
      kind === "not-listed"
        ? "mode=saf-puan&window=3"
        : kind === "different-selection"
          ? "mode=saf-puan&window=3"
          : "mode=saf-puan&window=1";
    render(
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[memberAddress(LEAGUE, ENTRY, `?${query}`)]}>
          {withLeague(<LeagueMemberView {...props} />)}
        </MemoryRouter>
      </LanguageProvider>,
    );
    const computeCopy = COMPUTE_COPY[language];
    const expected =
      kind === "published"
        ? computeCopy.serviceUnreachablePublished
        : kind === "not-listed" || kind === "declared-unavailable"
          ? computeCopy.serviceUnreachableAbsent
          : computeCopy.serviceUnreachable;
    expect(screen.getByText(expected)).toBeInTheDocument();
    for (const other of [
      computeCopy.serviceUnreachablePublished,
      computeCopy.serviceUnreachableAbsent,
      computeCopy.serviceUnreachable,
    ]) {
      if (other !== expected) expect(screen.queryByText(other)).not.toBeInTheDocument();
    }
  });

  it.each(["plan", "control", "both", "neither"] as const)(
    "shows no proof caveat when %s proof is unfinished",
    (kind) => {
      const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
      advice.payload.solver_status = kind === "plan" || kind === "both" ? "FEASIBLE" : "OPTIMAL";
      advice.payload.control_solver_status =
        kind === "control" || kind === "both" ? "FEASIBLE" : "OPTIMAL";
      const { container } = showAdvice(language, advice);
      expect(screen.getByText(copy.lineupTitle)).toBeInTheDocument();
      for (const sentence of PROOF_CAVEATS[language]) {
        expect(container.textContent).not.toMatch(sentence);
      }
    },
  );

  it.each(["missing", "unreadable"] as const)("distinguishes a %s member list", async (kind) => {
    reads.members.mockRejectedValue(
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
      reads.entrySquad.mockRejectedValue(
        kind === "missing"
          ? new data.LeagueDataMissing(`entries/${ENTRY}.json`)
          : new data.LeagueDataError("bad JSON"),
      );
      reads.entryAdviceIndex.mockReturnValue(new Promise(() => {}));
      open(language);
      expect(
        await screen.findByText(kind === "missing" ? copy.entryNotAvailable : copy.entryUnreadable),
      ).toBeInTheDocument();
      expect(screen.getByRole("link", { name: copy.backToMembers })).toHaveAttribute(
        "href",
        membersAddress(LEAGUE),
      );
      expect(
        screen.queryByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
      ).not.toBeInTheDocument();
      expect(reads.entryAdvice).not.toHaveBeenCalled();
    },
  );

  it("keeps a loaded squad visible while the index remains pending", async () => {
    reads.entryAdviceIndex.mockReturnValue(new Promise(() => {}));
    open(language);
    expect(
      await screen.findByRole("list", { name: MESSAGES[language].squad.pitchLabel }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.loadingAdvice)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.computeButton })).toBeDisabled();
    expect(reads.entryAdvice).not.toHaveBeenCalled();
  });

  it.each(["missing", "unreadable"] as const)(
    "distinguishes a listed advice file that is %s",
    async (kind) => {
      reads.entryAdvice.mockRejectedValue(
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
    reads.entryAdvice.mockReturnValue(
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
    reads.entryAdvice.mockRejectedValueOnce(new data.LeagueDataError("503")).mockReturnValueOnce(
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
    expect(reads.entryAdvice).toHaveBeenCalledTimes(2);
    expect(reads.entryAdvice).toHaveBeenNthCalledWith(1, ENTRY, "saf-puan", 1, null, {
      signal: expect.any(AbortSignal),
    });
    expect(reads.entryAdvice).toHaveBeenNthCalledWith(2, ENTRY, "saf-puan", 1, null, {
      signal: expect.any(AbortSignal),
    });
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

  it("says nothing about absent FEASIBLE gaps", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.solver_status = "FEASIBLE";
    advice.payload.control_solver_status = "FEASIBLE";
    advice.payload.optimality_gap = null;
    delete advice.payload.control_optimality_gap;
    const { container } = showAdvice(language, advice);
    expect(screen.getByText(copy.lineupTitle)).toBeInTheDocument();
    for (const sentence of PROOF_CAVEATS[language]) {
      expect(container.textContent).not.toMatch(sentence);
    }
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

  it("says nothing about measured zero gaps either", () => {
    const advice = structuredClone(mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    advice.payload.solver_status = "FEASIBLE";
    advice.payload.control_solver_status = "FEASIBLE";
    advice.payload.optimality_gap = 0;
    advice.payload.control_optimality_gap = 0;
    const { container } = showAdvice(language, advice);
    expect(screen.getByText(copy.lineupTitle)).toBeInTheDocument();
    for (const sentence of PROOF_CAVEATS[language]) {
      expect(container.textContent).not.toMatch(sentence);
    }
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
    { movement: "same", places: null, expected: "unknown" },
    { movement: "same", places: 0, expected: "same" },
    { movement: "up", places: 0, expected: "unknown" },
    { movement: "up", places: 1.5, expected: "unknown" },
    { movement: "down", places: -1, expected: "unknown" },
    { movement: "unknown", places: null, expected: "unknown" },
    { movement: "down", places: 2, expected: "down 2" },
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
          <MemoryRouter>{withLeague(<LeagueMembersView envelope={envelope} />)}</MemoryRouter>
        </LanguageProvider>,
      );
      const row = screen.getByRole("link", { name: member.manager_name! }).closest("tr")!;
      // Movement is the second column, after the rank; its words are its name.
      const movementCell = within(row).getAllByRole("cell")[1]!;
      expect(movementCell).toHaveAccessibleName(
        expected === "unknown"
          ? copy.noPreviousRank
          : expected === "same"
            ? copy.movementLabel("same", 0)
            : expected === "new"
              ? copy.newMember
              : copy.movementLabel("down", 2),
      );
    },
  );
});

describe.each(["tr", "en"] as const)("unavailable squad basis in %s", (language) => {
  it.each(["missing", "unreadable"] as const)(
    "keeps the backend reason only for a %s squad",
    async (kind) => {
      const reason = "Free Hit in GW3: pre-Free Hit GW2 picks document is missing. <b>capture</b>";
      const index = mockEntryAdviceIndex(ENTRY);
      reads.entryAdviceIndex.mockResolvedValue({
        ...index,
        payload: {
          ...index.payload,
          unavailable: [
            { strategy: "saf-puan", rival_entry_id: null, reason },
            { strategy: "ortak-koru", rival_entry_id: 123, reason },
          ],
        },
      });
      reads.entrySquad.mockRejectedValue(
        kind === "missing"
          ? new data.LeagueDataMissing(`entries/${ENTRY}.json`)
          : new data.LeagueDataError("bad JSON"),
      );
      open(language);
      expect(
        await screen.findByText(
          MESSAGES[language].leagueMembers[
            kind === "missing" ? "entryNotAvailable" : "entryUnreadable"
          ],
        ),
      ).toBeInTheDocument();
      if (kind === "missing") expect(await screen.findAllByText(reason)).toHaveLength(1);
      else expect(screen.queryByText(reason)).not.toBeInTheDocument();
      expect(screen.queryByText("capture", { selector: "b" })).not.toBeInTheDocument();
      expect(reads.entryAdvice).not.toHaveBeenCalled();
    },
  );

  it("names a plan that did not solve in the reader's language, never as its code", async () => {
    const copy = MESSAGES[language].leagueMembers;
    const index = mockEntryAdviceIndex(ENTRY);
    reads.entryAdviceIndex.mockResolvedValue({
      ...index,
      payload: {
        ...index.payload,
        unavailable: ["saf-puan", "ortak-koru", "fark-yarat"].map((strategy) => ({
          strategy,
          rival_entry_id: null,
          reason: "not_solved_for_member",
        })),
      },
    });
    reads.entrySquad.mockRejectedValue(new data.LeagueDataMissing(`entries/${ENTRY}.json`));
    open(language);
    expect(await screen.findByText(copy.entryNotAvailable)).toBeInTheDocument();
    const sentence = copy.publicationReasons.not_solved_for_member;
    expect(await screen.findAllByText(sentence)).toHaveLength(1);
    expect(screen.queryByText("not_solved_for_member")).not.toBeInTheDocument();
  });
});
