/**
 * Between a deadline and the next publish the page still shows the closed week's plan.
 * It has to say so, and it has to stop offering what only changes or recomputes that plan:
 * the plan's settings with Hesapla, the link down to them and the model comparison.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type { AdviceClient } from "../advice/adviceClient";
import { COMPUTE_COPY } from "../advice/computeCopy";
import { LeagueMemberView } from "./LeagueMemberPage";
import type { LeagueMemberViewProps } from "./memberPageTypes";
import { withLeague } from "../../../testSupport/league";

afterEach(cleanup);

const ENTRY = 35249001;
const DEADLINE = "2026-09-18T17:30:00Z";
const INDEX = mockEntryAdviceIndex(ENTRY).payload;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;

/** A service that computes both models, so the comparison is offered while the week is open. */
const CAPABILITIES: AdviceCapabilities = {
  leagueId: INDEX.league_id,
  captureSnapshotId: SQUAD.payload.source_snapshot_id!,
  season: INDEX.season,
  gameweek: INDEX.gameweek,
  strategies: {
    "saf-puan": { windows: [1, 3, 5], requiresRival: false },
    "ortak-koru": { windows: [1, 3], requiresRival: true },
  },
  models: ["current", "football"],
  top100Weights: [0],
  managersWord: false,
};

/** Has computed nothing, and is never asked to compute. */
const QUIET: AdviceClient = {
  readAdvice: async () => ({ kind: "not-computed" }),
  readPublished: async () => ({ kind: "not-computed" }),
  requestAdvice: () => Promise.reject(new Error("nothing is requested")),
  readJob: () => Promise.reject(new Error("nothing is polled")),
};

function renderView(
  deadlinePassed: string | null,
  language: "tr" | "en",
  search = "",
  props: Partial<LeagueMemberViewProps> = {},
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}${search}`]}>
        {withLeague(
          <LeagueMemberView
            index={INDEX}
            squad={SQUAD}
            advice={mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)}
            capabilities={CAPABILITIES}
            client={QUIET}
            deadlinePassed={deadlinePassed}
            {...props}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("a member page whose gameweek has closed", () => {
  it("says the deadline passed and names the gameweek", () => {
    for (const language of ["tr", "en"] as const) {
      const copy = COMPUTE_COPY[language];
      renderView(DEADLINE, language);
      expect(screen.getByText(copy.deadlinePassedTitle)).toBeInTheDocument();
      expect(screen.getByTestId("deadline-passed")).toHaveTextContent(copy.deadlinePassedTitle);
      cleanup();
    }
  });

  it("says it as one statement, not as a region and a heading with nothing under them", () => {
    const copy = COMPUTE_COPY.tr;
    renderView(DEADLINE, "tr");
    expect(screen.getByTestId("deadline-passed")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("region", { name: copy.deadlinePassedTitle })).toBeNull();
    expect(screen.queryByRole("heading", { name: copy.deadlinePassedTitle })).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "leaves out the settings, the link down to them and the model comparison (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const open = renderView(null, language);
      expect(open.container.querySelector("#plan-settings")).not.toBeNull();
      expect(screen.getByRole("link", { name: copy.changePlan })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: copy.computeButton })).toBeInTheDocument();
      cleanup();

      const closed = renderView(DEADLINE, language);
      // Once closed, the pitch shows the held team, not the expired recommendation.
      expect(screen.getByRole("heading", { name: copy.memberSquad })).toBeInTheDocument();
      expect(closed.container.querySelectorAll("#kadro [data-player-points]")).toHaveLength(0);
      expect(closed.container.querySelector("#plan-settings")).toBeNull();
      expect(screen.queryByRole("link", { name: copy.changePlan })).toBeNull();
      expect(screen.queryByRole("button", { name: copy.computeButton })).toBeNull();
    },
  );

  it("draws no card beside a selection the service would compute, open or under LIVE WEEK", () => {
    const copy = MESSAGES.tr.leagueMembers;
    // A rival strategy over three weeks: the publish solved one week, the service three.
    const search = "?mode=ortak-koru&window=3";
    const props: Partial<LeagueMemberViewProps> = {
      advice: null,
      adviceIssue: "not-listed",
      computeService: "ready",
    };
    renderView(null, "tr", search, props);
    // While the week is open the panel offers the computation and no card stands beside it.
    expect(screen.queryByText(copy.publicationStates["not-listed"].title)).toBeNull();
    cleanup();

    renderView(DEADLINE, "tr", search, props);
    // Under LIVE WEEK no plan is drawn, and no card names one.
    expect(screen.queryByText(copy.publicationStates["not-listed"].title)).toBeNull();
    expect(screen.queryByText(copy.adviceRequestHint)).toBeNull();
  });

  it.each(["index-error", "unavailable"] as const)(
    "draws no %s card under LIVE WEEK, where no plan is drawn to retry",
    (issue) => {
      const copy = MESSAGES.tr.leagueMembers;
      const props: Partial<LeagueMemberViewProps> = {
        advice: null,
        adviceIssue: issue,
        onRetryAdvice: () => undefined,
        onRetryIndex: () => undefined,
      };
      renderView(null, "tr", "", props);
      expect(screen.getByRole("button", { name: copy.retryPublishedRead })).toBeInTheDocument();
      cleanup();
      renderView(DEADLINE, "tr", "", props);
      expect(screen.queryByRole("button", { name: copy.retryPublishedRead })).toBeNull();
    },
  );

  it.each(["tr", "en"] as const)(
    "asks for no choice it no longer offers, and under LIVE WEEK names no plan (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const notListed = copy.publicationStates["not-listed"];
      const search = "?mode=ortak-koru&window=3";
      const props: Partial<LeagueMemberViewProps> = {
        advice: null,
        adviceIssue: "not-listed",
        capabilities: null,
      };
      renderView(null, language, search, props);
      // While the week is open the settings under the decision are where to choose.
      expect(screen.getByText(notListed.title)).toBeInTheDocument();
      expect(screen.getByText(notListed.body)).toBeInTheDocument();
      cleanup();

      renderView(DEADLINE, language, search, props);
      // The plan is not drawn under LIVE WEEK, so nothing says it is missing or points at one.
      expect(screen.queryByText(notListed.title)).toBeNull();
      expect(screen.queryByText(notListed.body)).toBeNull();
    },
  );

  it("says nothing while the deadline is open or unknown", () => {
    renderView(null, "en");
    expect(screen.queryByTestId("deadline-passed")).toBeNull();
  });

  it("sends the member to Hesapla for newer information only while the page has it", async () => {
    const plan = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    const snapshot = SQUAD.payload.source_snapshot_id!;
    const props: Partial<LeagueMemberViewProps> = {
      advice: null,
      computeService: "ready",
      capabilities: {
        ...CAPABILITIES,
        decisionInformation: {
          version: "football_decision_information_v1",
          revision: "d".repeat(64),
          source_snapshot_id: snapshot,
          observed_at: "2026-09-18T12:00:00Z",
          coach_news_bound: false,
          minute_components_bound: true,
        },
      },
      client: {
        ...QUIET,
        readAdvice: async () => ({
          kind: "advice",
          source: "api-cache",
          envelope: {
            ...plan,
            payload: {
              ...plan.payload,
              source_snapshot_id: snapshot,
              prediction_model: {
                id: "football",
                version: "football_team_share_v1",
                experimental: true,
                fingerprint: "c".repeat(64),
              },
            },
          },
        }),
      },
    };
    const copy = MESSAGES.tr.leagueMembers;
    renderView(null, "tr", "?model=football", props);
    await screen.findByText(copy.squadAfterTitle);
    expect(screen.getByTestId("new-information-notice")).toBeInTheDocument();
    cleanup();

    renderView(DEADLINE, "tr", "?model=football", props);
    await screen.findByRole("heading", { name: copy.memberSquad });
    expect(screen.queryByTestId("new-information-notice")).toBeNull();
    expect(screen.queryByRole("button", { name: copy.computeButton })).toBeNull();
  });
});

describe("the plan under LIVE WEEK", () => {
  /** The plan's details, drawn under the squad (AdviceDetails' holder, by its class here). */
  const details = () => [...document.querySelectorAll(".details")];

  it.each(["tr", "en"] as const)(
    "draws the closed week's plan neither as the decision nor as its details (%s)",
    async (language) => {
      const copy = MESSAGES[language].leagueMembers;
      // The open week draws the plan's board and its details.
      renderView(null, language);
      await screen.findByText(copy.squadAfterTitle);
      expect(details().length).toBeGreaterThan(0);
      cleanup();

      renderView(DEADLINE, language);
      await screen.findByRole("heading", { name: copy.liveWeek });
      expect(screen.getByRole("heading", { name: copy.memberSquad })).toBeInTheDocument();
      expect(screen.queryByText(copy.squadAfterTitle)).toBeNull();
      expect(details()).toEqual([]);
      expect(screen.queryByTestId("new-information-notice")).toBeNull();
    },
  );

  it.each(["tr", "en"] as const)(
    "says nothing is being read for the plan it does not draw (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      renderView(DEADLINE, language, "", { adviceLoading: true });
      expect(screen.getByRole("heading", { name: copy.liveWeek })).toBeInTheDocument();
      expect(screen.queryByText(copy.loadingAdvice)).toBeNull();
      cleanup();
      // The open week says so while its plan is read.
      renderView(null, language, "", { adviceLoading: true });
      expect(screen.getByText(copy.loadingAdvice)).toBeInTheDocument();
    },
  );
});

describe("a closed week on a device menu", () => {
  it.each(["tr", "en"] as const)(
    "shows no card under LIVE WEEK on a device menu either (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const props: Partial<LeagueMemberViewProps> = {
        advice: null,
        adviceIssue: "not-listed",
        capabilities: null,
        index: {
          ...INDEX,
          menu: "device",
          computed: [],
          unavailable: [],
          windows: { "saf-puan": [], "ortak-koru": [], "fark-yarat": [] },
        },
      };
      renderView(DEADLINE, language, "", props);
      expect(screen.getByTestId("deadline-passed")).toBeInTheDocument();
      expect(screen.queryByText(copy.publicationStates["not-listed"].title)).toBeNull();
    },
  );
});

describe("the closed week's heading", () => {
  it.each(["tr", "en"] as const)("is LIVE WEEK, with no plan summary under it (%s)", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    renderView(DEADLINE, language, "", { advice: null, adviceIssue: "not-listed" });
    const heading = screen.getByRole("heading", { name: copy.liveWeek });
    expect(heading).toHaveAttribute("data-live");
    expect(screen.queryByRole("heading", { name: copy.decisionTitle })).toBeNull();
    expect(screen.queryByTestId("member-selection-summary")).toBeNull();
  });

  it.each(["tr", "en"] as const)("carries no live mark while the week is open (%s)", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    renderView(null, language);
    const heading = screen.getByRole("heading", { name: copy.decisionTitle });
    expect(heading).not.toHaveAttribute("data-live");
    expect(screen.queryByRole("heading", { name: copy.liveWeek })).toBeNull();
  });
});
