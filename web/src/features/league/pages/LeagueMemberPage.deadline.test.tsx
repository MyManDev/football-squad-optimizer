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

const otherModel = { tr: "Diğer modeli de hesapla", en: "Compute the other model" } as const;

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

  it.each(["tr", "en"] as const)(
    "leaves out the settings, the link down to them and the model comparison (%s)",
    (language) => {
      const copy = MESSAGES[language].leagueMembers;
      const open = renderView(null, language);
      expect(open.container.querySelector("#plan-settings")).not.toBeNull();
      expect(screen.getByRole("link", { name: copy.changePlan })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: copy.computeButton })).toBeInTheDocument();
      cleanup();
      // The model comparison is on the decision tools' page.
      renderView(null, language, "", { tool: "decision-tools" });
      expect(screen.getByText(otherModel[language])).toBeInTheDocument();
      cleanup();

      const closed = renderView(DEADLINE, language);
      // The closed week's plan is still the page's answer.
      expect(screen.getByText(copy.squadAfterTitle)).toBeInTheDocument();
      expect(closed.container.querySelector("#plan-settings")).toBeNull();
      expect(screen.queryByRole("link", { name: copy.changePlan })).toBeNull();
      expect(screen.queryByRole("button", { name: copy.computeButton })).toBeNull();
      expect(screen.queryByText(COMPUTE_COPY[language].deadlinePassedCompute)).toBeNull();
      cleanup();
      // The decision tools only read the closed week, so their page stays, without the
      // comparison's computation.
      renderView(DEADLINE, language, "", { tool: "decision-tools" });
      expect(screen.getByRole("region", { name: copy.decisionTools })).toBeInTheDocument();
      expect(screen.queryByText(otherModel[language])).toBeNull();
    },
  );

  it("says what is published for a selection the service would have computed", () => {
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
    expect(screen.getByText(copy.closedNotListed.title)).toBeInTheDocument();
    expect(screen.queryByText(copy.adviceRequestHint)).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "asks for no choice it no longer offers, and links to the default plan instead (%s)",
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
      expect(screen.queryByRole("link", { name: copy.closedNotListed.link })).toBeNull();
      cleanup();

      renderView(DEADLINE, language, search, props);
      expect(screen.getByText(copy.closedNotListed.title)).toBeInTheDocument();
      expect(screen.getByText(copy.closedNotListed.body)).toBeInTheDocument();
      expect(screen.queryByText(notListed.body)).toBeNull();
      // The same page with no selection, as the sidebar's own link lands on it.
      expect(screen.getByRole("link", { name: copy.closedNotListed.link })).toHaveAttribute(
        "href",
        `/league/352490/members/${ENTRY}`,
      );
    },
  );

  it("says nothing while the deadline is open or unknown", () => {
    renderView(null, "en");
    expect(screen.queryByTestId("deadline-passed")).toBeNull();
    expect(screen.queryByText(COMPUTE_COPY.en.deadlinePassedCompute)).toBeNull();
  });
});
