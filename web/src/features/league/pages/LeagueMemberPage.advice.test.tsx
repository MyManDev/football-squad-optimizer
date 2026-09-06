/**
 * Hesapla reaches the card: a member whose published advice is missing keeps the compute
 * control; a computed answer lands in the advice card with its origin; a failure leaves the
 * published plan standing; a changed selection never wears an earlier selection's answer.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestResult,
} from "../advice/adviceClient";
import type { AdviceMove, EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView, type AdviceIssue } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const COMPUTED_MOVE: AdviceMove = {
  move_id: "computed-1",
  player_out: {
    player_id: 901,
    name: "Static Winger",
    short_name: "Winger",
    position: "MID",
    team: "HAR",
  },
  player_in: {
    player_id: 902,
    name: "Computed Striker",
    short_name: "Striker",
    position: "FWD",
    team: "HAR",
  },
  expected_points_delta: 2.5,
  expected_points_cost: 0,
  reason_code: "window_value",
};

function computedEnvelope(): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return {
    ...base,
    generated_at_utc: "2026-09-06T10:00:00Z",
    payload: { ...base.payload, source_snapshot_id: "fpl-live-computed", moves: [COMPUTED_MOVE] },
  };
}

class FakeClient implements AdviceClient {
  private readonly outcome: () => Promise<AdviceRequestResult>;

  constructor(outcome: () => Promise<AdviceRequestResult>) {
    this.outcome = outcome;
  }

  async readAdvice(_request: AdviceRequest): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }

  requestAdvice(_request: AdviceRequest): Promise<AdviceRequestResult> {
    return this.outcome();
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    return { jobId, status: "failed" };
  }
}

function SwitchMode() {
  const [params, setParams] = useSearchParams();
  return (
    <button
      type="button"
      onClick={() => {
        const next = new URLSearchParams(params);
        next.set("mode", "garantici");
        setParams(next);
      }}
    >
      switch-mode
    </button>
  );
}

function renderView({
  advice,
  adviceIssue,
  client,
}: {
  advice: LeagueViewEnvelope<EntryAdvice> | null;
  adviceIssue?: AdviceIssue;
  client: AdviceClient;
}) {
  return render(
    <LanguageProvider initialLanguage="tr">
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
        <SwitchMode />
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
          adviceIssue={adviceIssue}
          members={MEMBERS}
          client={client}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

async function compute(): Promise<void> {
  await act(async () => {
    screen.getByRole("button", { name: "Hesapla" }).click();
    await Promise.resolve();
  });
}

describe("league member advice flow", () => {
  it("keeps the compute control when the published advice is missing", () => {
    renderView({
      advice: null,
      adviceIssue: "not-computed",
      client: new FakeClient(async () => ({ kind: "unavailable" })),
    });

    expect(screen.getByRole("button", { name: "Hesapla" })).toBeInTheDocument();
    expect(screen.getByText("Bu mod ve ufuk bu yayın için hesaplanmadı.")).toBeInTheDocument();
    expect(screen.getByText("Yukarıdaki Hesapla ile isteyebilirsin.")).toBeInTheDocument();
  });

  it("shows the computed moves in the advice card with their origin", async () => {
    renderView({
      advice: null,
      adviceIssue: "not-computed",
      client: new FakeClient(async () => ({
        kind: "advice",
        envelope: computedEnvelope(),
        source: "api-cache",
      })),
    });

    await compute();

    expect(await screen.findByText("Computed Striker")).toBeInTheDocument();
    expect(screen.getByText("Şimdi hesaplandı")).toBeInTheDocument();
    expect(screen.getByText("Hesaplandı")).toBeInTheDocument();
    expect(screen.getByText(/Capture fpl-live-computed/)).toBeInTheDocument();
    expect(screen.queryByText("Bu mod ve ufuk bu yayın için hesaplanmadı.")).toBeNull();
  });

  it("leaves the published plan standing when the request fails", async () => {
    const published = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    renderView({
      advice: published,
      client: new FakeClient(async () => {
        throw new Error("backend down");
      }),
    });

    await compute();

    expect(await screen.findByText(/Hesap tamamlanamadı/)).toBeInTheDocument();
    expect(
      screen.getByText(published.payload.moves.length === 0 ? /hamle yok/ : /Çıkan/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Şimdi hesaplandı")).toBeNull();
  });

  it("does not carry a computed answer over to a changed selection", async () => {
    renderView({
      advice: mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1),
      client: new FakeClient(async () => ({
        kind: "advice",
        envelope: computedEnvelope(),
        source: "api-cache",
      })),
    });
    await compute();
    expect(await screen.findByText("Computed Striker")).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "switch-mode" }).click();
      await Promise.resolve();
    });

    expect(screen.queryByText("Computed Striker")).toBeNull();
    expect(screen.queryByText("Şimdi hesaplandı")).toBeNull();
    expect(screen.queryByText("Hesaplandı")).toBeNull();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
  });
});
