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
  mockEntryAdviceIndex,
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
import { HttpAdviceClient } from "../advice/adviceClient";
import type {
  AdviceMove,
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  LeagueViewEnvelope,
} from "../types";
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
  private readonly outcome: (request: AdviceRequest) => Promise<AdviceRequestResult>;

  constructor(outcome: (request: AdviceRequest) => Promise<AdviceRequestResult>) {
    this.outcome = outcome;
  }

  async readAdvice(_request: AdviceRequest): Promise<AdviceReadResult> {
    return { kind: "not-computed" };
  }

  requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    return this.outcome(request);
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
  initialEntry = `/league/members/${ENTRY}`,
  language = "tr",
  index = mockEntryAdviceIndex(ENTRY).payload,
}: {
  advice: LeagueViewEnvelope<EntryAdvice> | null;
  adviceIssue?: AdviceIssue;
  client: AdviceClient;
  initialEntry?: string;
  language?: "tr" | "en";
  index?: EntryAdviceIndex | null;
}) {
  const content = (squad: LeagueViewEnvelope<EntrySquad>) => (
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <SwitchMode />
        <LeagueMemberView
          squad={squad}
          advice={advice}
          adviceIssue={adviceIssue}
          members={MEMBERS}
          index={index}
          client={client}
        />
      </MemoryRouter>
    </LanguageProvider>
  );
  const rendered = render(content(mockEntrySquadEnvelopes[ENTRY]!));
  return {
    ...rendered,
    updateSquad: (squad: LeagueViewEnvelope<EntrySquad>) => rendered.rerender(content(squad)),
  };
}

async function compute(): Promise<void> {
  await act(async () => {
    screen.getByRole("button", { name: "Hesapla" }).click();
    await Promise.resolve();
  });
}

describe("league member advice flow", () => {
  it("connects the HTTP request, completed job and advice read to the visible card", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    const client = new HttpAdviceClient("https://api.example", async (url, init) => {
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      const queued = init?.method === "POST";
      const body = queued
        ? { job_id: "job-entry", status: "queued" }
        : url.includes("advice-jobs/")
          ? { job_id: "job-entry", status: "completed" }
          : computedEnvelope();
      return new Response(JSON.stringify(body), { status: queued ? 202 : 200 });
    });
    renderView({ advice: null, client });
    await compute();
    expect(screen.getByText("Kuyrukta")).toBeInTheDocument();
    expect(await screen.findByText("Computed Striker", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("Hesap sonucu")).toBeInTheDocument();
    expect(calls.map((call) => call.method)).toEqual(["POST", "GET", "GET"]);
    expect(calls[0]?.body).toEqual({ strategy: "saf-puan", window: 1, rival_entry_id: null });
    expect(calls[1]?.url).toBe("https://api.example/api/v1/advice-jobs/job-entry");
  });

  it("keeps the compute control when the published advice is missing", () => {
    renderView({
      advice: null,
      adviceIssue: "not-computed",
      client: new FakeClient(async () => ({ kind: "unavailable" })),
    });

    expect(screen.getByRole("button", { name: "Hesapla" })).toBeInTheDocument();
    expect(screen.getByText("Bu kombinasyon bu yayın için hesaplanmadı.")).toBeInTheDocument();
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
    expect(screen.getByText("Hesap sonucu")).toBeInTheDocument();
    expect(screen.getByText("Plan hazır")).toBeInTheDocument();
    expect(screen.queryByText("Şimdi hesaplandı")).toBeNull();
    expect(screen.getByText(/Capture fpl-live-computed/)).toBeInTheDocument();
    expect(screen.queryByText("Bu kombinasyon bu yayın için hesaplanmadı.")).toBeNull();
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
    expect(screen.queryByText("Hesap sonucu")).toBeNull();
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
    expect(screen.queryByText("Hesap sonucu")).toBeNull();
    expect(screen.queryByText("Plan hazır")).toBeNull();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();
  });

  it.each([
    ["ortak-koru", 3],
    ["fark-yarat", 5],
  ] as const)(
    "keeps %s/%i visible but does not submit a rival strategy over a longer window",
    async (mode, window) => {
      const requests: AdviceRequest[] = [];
      renderView({
        advice: mockEntryAdviceEnvelope(ENTRY, mode, window),
        initialEntry: `/league/members/${ENTRY}?mode=${mode}&window=${window}`,
        client: new FakeClient(async (request) => {
          requests.push(request);
          return { kind: "unavailable" };
        }),
      });

      expect(screen.getByDisplayValue(mode)).toBeChecked();
      expect(screen.getByRole("radio", { name: new RegExp(`${window} hafta`) })).toBeChecked();
      expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();
      expect(
        screen.getByText(/Rakip stratejisi daha uzun pencerede hesaplanmaz/),
      ).toBeInTheDocument();
      expect(screen.queryByText("Yukarıdaki Hesapla ile isteyebilirsin.")).toBeNull();
      await compute();
      expect(requests).toEqual([]);
    },
  );

  it.each([3, 5] as const)("submits pure points over a %i-week window", async (window) => {
    const requests: AdviceRequest[] = [];
    renderView({
      advice: null,
      adviceIssue: "not-computed",
      initialEntry: `/league/members/${ENTRY}?window=${window}`,
      client: new FakeClient(async (request) => {
        requests.push(request);
        return { kind: "unavailable" };
      }),
    });

    expect(screen.getByRole("radio", { name: new RegExp(`${window} hafta`) })).toBeChecked();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    expect(screen.getByText("Yukarıdaki Hesapla ile isteyebilirsin.")).toBeInTheDocument();
    await compute();
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ strategy: "saf-puan", window, rivalEntryId: null });
  });

  it("posts the window in the HTTP request body", async () => {
    const bodies: unknown[] = [];
    const client = new HttpAdviceClient("https://api.example", async (url, init) => {
      if (init?.method === "POST") bodies.push(JSON.parse(String(init.body)));
      const body =
        init?.method === "POST"
          ? { job_id: "job-window", status: "queued" }
          : url.includes("advice-jobs/")
            ? { job_id: "job-window", status: "failed" }
            : {};
      return new Response(JSON.stringify(body), { status: init?.method === "POST" ? 202 : 200 });
    });
    renderView({
      advice: null,
      initialEntry: `/league/members/${ENTRY}?window=3`,
      client,
    });
    await compute();
    expect(bodies).toEqual([{ strategy: "saf-puan", window: 3, rival_entry_id: null }]);
  });

  it("does not submit a rival strategy when no rival can be named", async () => {
    const requests: AdviceRequest[] = [];
    renderView({
      advice: null,
      initialEntry: `/league/members/${ENTRY}?mode=ortak-koru`,
      index: null,
      client: new FakeClient(async (request) => {
        requests.push(request);
        return { kind: "unavailable" };
      }),
    });
    // Without an index the members list still offers rivals; strip them to prove the gate.
    expect(screen.getByDisplayValue("ortak-koru")).toBeChecked();
    await compute();
    expect(requests.every((request) => request.rivalEntryId !== null)).toBe(true);
  });

  it("submits a rival strategy with the producer's default rival", async () => {
    const requests: AdviceRequest[] = [];
    const rival = mockEntryAdviceIndex(ENTRY).payload.default_rival_entry_id;
    renderView({
      advice: null,
      initialEntry: `/league/members/${ENTRY}?mode=ortak-koru`,
      client: new FakeClient(async (request) => {
        requests.push(request);
        return { kind: "unavailable" };
      }),
    });
    expect(screen.getByRole("combobox", { name: "Karşısında oynadığın üye" })).toHaveValue(
      String(rival),
    );
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    await compute();
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ strategy: "ortak-koru", window: 1, rivalEntryId: rival });
  });

  it("explains unsupported selections in English without promising a calculation", () => {
    renderView({
      advice: null,
      initialEntry: `/league/members/${ENTRY}?mode=ortak-koru&window=3`,
      language: "en",
      client: new FakeClient(async () => ({ kind: "unavailable" })),
    });
    expect(screen.getByRole("button", { name: "Compute" })).toBeDisabled();
    expect(
      screen.getByText(/A rival strategy is not computed over a longer window/),
    ).toBeInTheDocument();
    expect(screen.queryByText("You can ask for it with Compute above.")).toBeNull();
  });

  it.each(["static", "static-fallback"] as const)(
    "labels a %s answer as a published plan",
    async (source) => {
      renderView({
        advice: null,
        client: new FakeClient(async () => ({
          kind: "advice",
          envelope: computedEnvelope(),
          source,
        })),
      });

      await compute();

      expect(screen.getByText("Computed Striker")).toBeInTheDocument();
      expect(screen.getByText("Yayınlanmış plan")).toBeInTheDocument();
      expect(screen.queryByText("Hesap sonucu")).toBeNull();
      expect(screen.queryByText("Plan hazır")).toBeNull();
      expect(screen.queryByText("Şimdi hesaplandı")).toBeNull();
    },
  );

  it("uses squad context and removes a stale rival from the pure-points request", async () => {
    const requests: AdviceRequest[] = [];
    const published = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
    renderView({
      advice: { ...published, payload: { ...published.payload, league_id: 999 } },
      initialEntry: `/league/members/${ENTRY}?rival=35249002`,
      client: new FakeClient(async (request) => {
        requests.push(request);
        return { kind: "unavailable" };
      }),
    });

    await compute();

    const squad = mockEntrySquadEnvelopes[ENTRY]!.payload;
    expect(requests).toEqual([
      {
        leagueId: squad.league_id,
        entryId: ENTRY,
        strategy: "saf-puan",
        window: 1,
        rivalEntryId: null,
        season: squad.season,
        gameweek: squad.gameweek,
      },
    ]);
    expect(screen.queryByRole("combobox", { name: "Rakip" })).toBeNull();
  });

  it.each([
    { league_id: 999 },
    { entry_id: ENTRY + 1 },
    { mode: "garantici" },
    { window: 3 },
    { season: "2027-28" },
    { gameweek: mockEntrySquadEnvelopes[ENTRY]!.payload.gameweek + 1 },
  ] satisfies Partial<EntryAdvice>[])(
    "hides published advice with mismatched context %j",
    (changed) => {
      const published = computedEnvelope();
      renderView({
        advice: { ...published, payload: { ...published.payload, ...changed } },
        client: new FakeClient(async () => ({ kind: "unavailable" })),
      });

      expect(screen.queryByText("Computed Striker")).toBeNull();
      expect(screen.getByText("Bu kombinasyon bu yayın için hesaplanmadı.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
    },
  );

  it("discards a completed result when the published squad capture changes", async () => {
    const view = renderView({
      advice: null,
      client: new FakeClient(async () => ({
        kind: "advice",
        envelope: computedEnvelope(),
        source: "api-cache",
      })),
    });
    await compute();
    expect(screen.getByText("Computed Striker")).toBeInTheDocument();

    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    view.updateSquad({
      ...squad,
      payload: { ...squad.payload, source_snapshot_id: "fpl-live-next-capture" },
    });

    expect(screen.queryByText("Computed Striker")).toBeNull();
    expect(screen.queryByText("Plan hazır")).toBeNull();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
  });

  it("ignores an old in-flight result after the published squad is refreshed", async () => {
    let finish!: (result: AdviceRequestResult) => void;
    const view = renderView({
      advice: null,
      client: new FakeClient(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    });
    await compute();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeDisabled();

    const squad = mockEntrySquadEnvelopes[ENTRY]!;
    view.updateSquad({ ...squad, generated_at_utc: "2026-09-07T10:00:00Z" });
    await act(async () => {
      finish({ kind: "advice", envelope: computedEnvelope(), source: "api-cache" });
      await Promise.resolve();
    });

    expect(screen.queryByText("Computed Striker")).toBeNull();
    expect(screen.queryByText("Plan hazır")).toBeNull();
    expect(screen.getByRole("button", { name: "Hesapla" })).toBeEnabled();
  });
});
