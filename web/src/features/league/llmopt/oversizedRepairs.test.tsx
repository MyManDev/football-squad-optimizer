import { webcrypto } from "node:crypto";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { AdviceClient, AdviceRequest } from "../advice/adviceClient";
import { preferenceScope } from "../advice/decisionPreferences";
import { LLMOPT_COPY } from "./copy";
import { type Constraint, type PlanDraft } from "./intent";
import { summarizeRevision } from "./planRevision";
import { VerifiedRuleRepairs } from "./VerifiedRuleRepairs";

const squad = mockEntrySquadEnvelopes[35249001]!.payload;
const example = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
const starters = example.payload.starting_xi!;
const small = {
  starting_xi: starters,
  bench: example.payload.bench!,
  captain: starters[0]!,
  vice_captain: starters[1]!,
};
const incoming = [...starters, ...small.bench].map((p, i) => ({
  ...p,
  player_id: 8_000_000_000_000 + i,
}));
const outgoing = incoming.map((p) => ({ ...p, player_id: p.player_id - 100 }));
const large = {
  starting_xi: incoming.slice(0, 11),
  bench: incoming.slice(11),
  captain: incoming[0]!,
  vice_captain: incoming[1]!,
};
function answer(fixed: boolean) {
  return {
    ...example.payload,
    ...small,
    plan_data_id: "b".repeat(64),
    source_snapshot_id: squad.source_snapshot_id,
    plan_weeks: example.payload.plan_weeks!.map((row, i) => ({
      ...row,
      chip: null,
      lineup: fixed && !i ? large : small,
      transfer_hit_points: 0,
      transfers_in: fixed && !i ? incoming : [],
      transfers_out: fixed && !i ? outgoing : [],
    })),
  };
}
const reference = summarizeRevision(answer(true));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function show(width: number, includeSecond: boolean, language: "en" | "tr" = "en") {
  vi.stubGlobal("crypto", webcrypto);
  const clubs: Constraint[] = Array.from({ length: 12 }, (_, i) => ({
    kind: "club_count",
    club: "Ş".repeat(width) + i,
    count: 1,
  }));
  const sourceDraft: PlanDraft = {
    hard: [...clubs, { kind: "no_hits" }],
    soft: [],
    window: 3,
    keep_weeks: [1],
  };
  const owner = { runId: "a".repeat(32), dataId: "b".repeat(64), failedBase: false, sourceDraft };
  const first = { label: "Remove hit limit", draft: { ...sourceDraft, hard: clubs } };
  const second = { label: "Unlock opening week", draft: { ...sourceDraft, keep_weeks: [] } };
  const requestAdvice = vi.fn(async (request: AdviceRequest) => ({
    kind: "advice" as const,
    source: "api-cache" as const,
    envelope: {
      ...example,
      payload: {
        ...answer(Boolean(request.preferences?.frozen_weeks?.[0]?.transfers_in.length)),
        preferences: request.preferences,
        preferences_scope: preferenceScope(request.preferences),
      },
    },
  }));
  const client: AdviceClient = {
    requestAdvice,
    readJob: vi.fn(),
    readAdvice: vi.fn(),
    readPublished: vi.fn(),
  };
  const apply = vi.fn();
  render(
    <LanguageProvider initialLanguage={language}>
      <VerifiedRuleRepairs
        analysis={{
          status: "conflict",
          sentence: LLMOPT_COPY[language].repairs.conflict,
          choices: includeSecond ? [first, second] : [first],
        }}
        client={client}
        squad={squad}
        window={3}
        reference={reference}
        disabled={false}
        begin={async () => owner}
        current={async () => true}
        apply={apply}
      />
    </LanguageProvider>,
  );
  return { requestAdvice, apply };
}

it.each([
  { width: 38, expectedStages: ["base"] },
  { width: 32, expectedStages: ["base", "repair"] },
])(
  "checks the next independent edit when the first candidate or its replay exceeds the wire limit ($width)",
  async ({ width, expectedStages }) => {
    const { requestAdvice, apply } = show(width, true);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: LLMOPT_COPY.en.repairs.check }));
    const verified = await screen.findByRole("button", { name: "Unlock opening week" });
    expect(screen.queryByRole("button", { name: "Remove hit limit" })).toBeNull();
    expect(requestAdvice.mock.calls.map(([request]) => request.run?.stage)).toEqual(expectedStages);
    await user.click(verified);
    await waitFor(() => expect(apply).toHaveBeenCalledOnce());
  },
);

it.each(["en", "tr"] as const)(
  "asks for a smaller request in %s if no candidate fits",
  async (language) => {
    const { requestAdvice } = show(60, true, language);
    const copy = LLMOPT_COPY[language].repairs;
    await userEvent.click(screen.getByRole("button", { name: copy.check }));
    expect(await screen.findByText(copy.tooLarge)).toBeVisible();
    expect(requestAdvice).not.toHaveBeenCalled();
  },
);
