import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { DecisionPreferencesPanel } from "./DecisionPreferencesPanel";
import { checkedPreferences, preferencesFromUrl, preferencesKey } from "./decisionPreferences";
import { adviceRequestKey } from "./adviceJobStore";
import { checkedAdvice } from "./adviceResponse";
import { decisionParams } from "./decisionBoard";
import { sameAdviceRequest } from "./useAdviceJob";
import { resolvePublishedAdvice } from "./adviceSelection";
import { HttpAdviceClient, StaticOnlyAdviceClient, type AdviceRequest } from "./adviceClient";

const entry = 35249001;
const squad = mockEntrySquadEnvelopes[entry]!.payload;
const base: AdviceRequest = { leagueId: 352490, entryId: entry, strategy: "saf-puan", window: 3 };
const p = checkedPreferences({ keep_players: [squad.starting_xi[0]!.player_id], no_hits: true });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("keeps request, waiting job and board identities distinct and reopens the exact constraints", () => {
  const request = { ...base, preferences: p };
  expect(adviceRequestKey(request)).not.toBe(adviceRequestKey(base));
  expect(sameAdviceRequest(request, base)).toBe(false);
  const url = decisionParams(new URLSearchParams(), request);
  expect(preferencesFromUrl(url).value).toEqual(p);
  expect(decisionParams(url, base).has("preferences")).toBe(false);
  expect(preferencesKey(checkedPreferences({ keep_players: [3, 1] }))).toBe(
    preferencesKey(checkedPreferences({ keep_players: [1, 3] })),
  );
});

it("refuses conflicting or malformed URL constraints without displaying the ordinary plan", () => {
  const index = mockEntryAdviceIndex(entry).payload;
  for (const raw of [
    "{",
    '{"no_hits":1}',
    '{"keep_players":[1],"avoid_players":[1]}',
    JSON.stringify(p),
  ]) {
    const params = new URLSearchParams({ preferences: raw, mode: "saf-puan", window: "3" });
    const result = resolvePublishedAdvice(
      params,
      base.leagueId,
      entry,
      mockLeagueMembersEnvelope.payload.members,
      index,
    );
    expect(result.status).toBe("not-listed");
    expect(result.path).toBeNull();
    expect(result.computable?.selection).not.toBe(true);
  }
});

it("rejects a response for different preferences and never uses a static fallback", async () => {
  const envelope = mockEntryAdviceEnvelope(entry, "saf-puan", 3);
  const request = { ...base, preferences: p };
  expect(() => checkedAdvice(envelope, request)).toThrow(/preferences/);
  const withPreferences = {
    ...envelope,
    payload: { ...envelope.payload, preferences: p, preferences_scope: "all_selected_weeks" },
  };
  expect(checkedAdvice(withPreferences, request)).toEqual(withPreferences);
  expect(() => checkedAdvice(withPreferences, base)).toThrow(/preferences/);
  const loader = vi.fn();
  expect(await new StaticOnlyAdviceClient(loader).readAdvice(request)).toEqual({
    kind: "not-computed",
  });
  expect(loader).not.toHaveBeenCalled();
});

it("puts identical preferences on POST and cache GET", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const client = new HttpAdviceClient("https://api.example", async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(
      JSON.stringify(
        init?.method === "POST"
          ? { job_id: "preference-job" }
          : { error: { code: "NOT_COMPUTED" } },
      ),
      { status: init?.method === "POST" ? 202 : 404 },
    );
  });
  await client.requestAdvice({ ...base, preferences: p });
  await client.readAdvice({ ...base, preferences: p });
  expect(JSON.parse(String(calls[0]!.init!.body)).preferences).toEqual(p);
  expect(JSON.parse(new URL(calls[1]!.url).searchParams.get("preferences")!)).toEqual(p);
});

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}
it("selects team, position and player; keeps choices in the URL and clears chip conflicts explicitly", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          season: squad.season,
          players: [{ id: 99991, name: "Avoid Me", team: "Test Team", position: "MID" }],
        }),
      ),
    ),
  );
  render(
    <LanguageProvider>
      <MemoryRouter initialEntries={["/?chip=auto"]}>
        <DecisionPreferencesPanel squad={squad} available />
        <Location />
      </MemoryRouter>
    </LanguageProvider>,
  );
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "Test Team" })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText(/Avoid player's team|Alınmayacak oyuncunun takımı/), {
    target: { value: "Test Team" },
  });
  fireEvent.change(screen.getByLabelText(/Position|Pozisyon/), { target: { value: "MID" } });
  fireEvent.change(screen.getByLabelText(/^Avoid player$|^Kadroya alma$/), {
    target: { value: "99991" },
  });
  fireEvent.click(screen.getByLabelText(/Save chips throughout|Çipleri pencere boyunca/));
  const params = new URLSearchParams(screen.getByTestId("location").textContent!);
  expect(params.has("chip")).toBe(false);
  expect(preferencesFromUrl(params).value).toMatchObject({
    avoid_players: [99991],
    save_chips: true,
  });
});
