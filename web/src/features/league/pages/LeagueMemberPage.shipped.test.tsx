/**
 * Every member page, drawn from the league tree that is actually committed.
 *
 * Every other member-page test reads example documents, and the one test that reads the
 * real tree (`shippedTree.test.ts`) runs validators without drawing anything. A component
 * that throws on a real document shape the examples never carry would reach a member
 * first. This draws the page as the site does, for every member in
 * `public/data/league/members.json` and in both languages: the real loaders, the real
 * validators, the shell and the route's error boundary, with each request answered from
 * `public/` on disk. Nothing leaves the process, and a request outside `data/` fails the
 * test.
 *
 * The loaders serve examples to tests unconditionally, so the build's environment is
 * stubbed to production for these tests: they read the published path, and an example
 * fallback throws instead of hiding a missing document.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RouteErrorBoundary } from "../../../app/RouteErrorBoundary";
import { PageShell } from "../../../design/components/PageShell";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { isRefusedMemberIndex, refusedMemberIndex } from "../../../testSupport/refusedMember";
import { resolvePublishedAdvice } from "../advice/adviceSelection";
import type {
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  LeagueMembers,
  LeagueViewEnvelope,
} from "../types";
import { LeagueMemberPage } from "./LeagueMemberPage";

const PUBLIC = join(__dirname, "../../../../public");
const LEAGUE = "data/league";

function readPublished<T>(relative: string): T {
  return JSON.parse(readFileSync(join(PUBLIC, relative), "utf-8")) as T;
}

const shipped = existsSync(join(PUBLIC, LEAGUE, "members.json"));
const league = shipped
  ? readPublished<LeagueViewEnvelope<LeagueMembers>>(`${LEAGUE}/members.json`).payload
  : null;
const humans = (league?.members ?? []).flatMap((member) =>
  member.member_kind === "human" ? [member.entry_id] : [],
);

/** Published paths answered with something else, or (null) as not published. */
const overrides = new Map<string, string | null>();
/** Every address the page asked for that is not a published document. */
const strays: string[] = [];
const clients: QueryClient[] = [];
let consoleErrors: unknown[][] = [];

beforeEach(() => {
  vi.stubEnv("MODE", "production");
  vi.stubEnv("DEV", false);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const address = input instanceof Request ? input.url : String(input);
      const base = import.meta.env.BASE_URL;
      const relative = address.startsWith(base) ? address.slice(base.length) : null;
      if (
        relative === null ||
        !relative.startsWith("data/") ||
        relative.split("/").includes("..")
      ) {
        strays.push(address);
        throw new TypeError(`No network in this test: ${address}`);
      }
      if (overrides.has(relative)) {
        const body = overrides.get(relative);
        return body == null ? new Response("", { status: 404 }) : new Response(body);
      }
      const path = join(PUBLIC, relative);
      if (!existsSync(path)) return new Response("", { status: 404 });
      return new Response(readFileSync(path, "utf-8"), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  const original = console.error;
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args);
    original(...args);
  });
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  overrides.clear();
  strays.length = 0;
  consoleErrors = [];
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function openMemberPage(entryId: number, language: Language) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[`/league/members/${entryId}`]}>
          <PageShell>
            <RouteErrorBoundary>
              <Routes>
                <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
              </Routes>
            </RouteErrorBoundary>
          </PageShell>
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const WAIT = { timeout: 20_000 };

/** What the page may say about itself that is a failure rather than a published state. */
function failureCopy(language: Language): string[] {
  const copy = MESSAGES[language].leagueMembers;
  return [
    MESSAGES[language].common.pageFailed,
    copy.entryUnreadable,
    copy.membersUnreadable,
    copy.notAvailable,
    copy.loadingEntry,
  ];
}

function expectNoFailure(language: Language) {
  for (const text of failureCopy(language)) expect(screen.queryByText(text)).toBeNull();
  expect(strays).toEqual([]);
  expect(consoleErrors).toEqual([]);
}

async function expectNotAvailable(language: Language, reason: string) {
  const copy = MESSAGES[language].leagueMembers;
  expect(await screen.findByText(copy.entryNotAvailable, undefined, WAIT)).toBeInTheDocument();
  expect(screen.getByText(copy.entryNotAvailableBody)).toBeInTheDocument();
  // The reason arrives with the index, which may land after the missing squad.
  if (reason) expect(await screen.findByText(reason, undefined, WAIT)).toBeInTheDocument();
  expectNoFailure(language);
}

/**
 * Open a member's page and hold it to what the tree promises: a refused member says it is
 * not available and why; any other draws its team as the page's heading and, under the
 * decision heading, the plan the index names with no settings chosen (one board per move,
 * or the no-transfer line), with no failure anywhere on the page.
 */
async function expectMemberDrawn(entryId: number, language: Language) {
  const copy = MESSAGES[language].leagueMembers;
  const index = readPublished<LeagueViewEnvelope<EntryAdviceIndex>>(
    `${LEAGUE}/advice/${entryId}/index.json`,
  ).payload;
  openMemberPage(entryId, language);

  if (!existsSync(join(PUBLIC, LEAGUE, `entries/${entryId}.json`)) && isRefusedMemberIndex(index)) {
    await expectNotAvailable(language, index.unavailable[0]!.reason);
    return;
  }

  const squad = readPublished<LeagueViewEnvelope<EntrySquad>>(
    `${LEAGUE}/entries/${entryId}.json`,
  ).payload;
  const team = squad.entry.team_name ?? copy.unknownTeam;
  expect(await screen.findByRole("heading", { level: 1, name: team }, WAIT)).toBeInTheDocument();
  const decision = screen
    .getByRole("heading", { level: 2, name: copy.decisionTitle })
    .closest<HTMLElement>('[data-mark="decision"]')!;
  expect(decision).not.toBeNull();
  await waitFor(() => expect(within(decision).queryByText(copy.loadingAdvice)).toBeNull(), WAIT);

  const selection = resolvePublishedAdvice(
    new URLSearchParams(),
    squad.league_id,
    entryId,
    league!.members,
    index,
    { season: squad.season, gameweek: squad.gameweek },
  );
  expect(selection.status).toBe("ready");
  const plan = readPublished<LeagueViewEnvelope<EntryAdvice>>(
    `${LEAGUE}/${selection.path!}`,
  ).payload;

  // The decision is drawn, not a card saying why it is not.
  const missing = [
    copy.adviceNotComputed,
    copy.adviceUnreadable,
    ...Object.values(copy.publicationStates).map((state) => state.title),
  ];
  for (const text of missing) expect(within(decision).queryByText(text)).toBeNull();
  if (plan.moves.length === 0) {
    expect(
      within(decision).queryByText(copy.noMove) ??
        within(decision).queryByText(copy.noPlanInRecord),
    ).not.toBeNull();
  } else {
    plan.moves.forEach((_, position) => {
      expect(
        within(decision).getByRole("heading", {
          level: 3,
          name: copy.boardChange(position + 1, plan.moves.length),
        }),
      ).toBeInTheDocument();
    });
  }
  expectNoFailure(language);
}

describe.skipIf(!shipped)("every member page, from the published tree", () => {
  describe.each(["tr", "en"] as const)("in %s", (language) => {
    it.each(humans)("draws member %i with its heading and its decision", async (entryId) => {
      await expectMemberDrawn(entryId, language);
    });

    it("draws a member the producer refused as not available, with the reason", async () => {
      // The refusal is laid over a real member, so this runs whether or not the tree holds
      // one: the member list reports no advice, no squad is published, and the index is the
      // one the producer writes.
      const entryId = humans[0]!;
      const reason = `Entry ${entryId} played a Free Hit in gameweek ${league!.gameweek - 1}.`;
      const members = readPublished<LeagueViewEnvelope<LeagueMembers>>(`${LEAGUE}/members.json`);
      for (const row of members.payload.members) {
        if (row.entry_id === entryId) row.data_quality = "empty";
      }
      const refused: LeagueViewEnvelope<EntryAdviceIndex> = {
        ...members,
        payload: refusedMemberIndex({
          leagueId: league!.league_id,
          season: league!.season,
          gameweek: league!.gameweek,
          entryId,
          rivalEntryIds: humans.filter((id) => id !== entryId).slice(0, 1),
          reason,
        }),
      };
      overrides.set(`${LEAGUE}/members.json`, JSON.stringify(members));
      overrides.set(`${LEAGUE}/entries/${entryId}.json`, null);
      overrides.set(`${LEAGUE}/advice/${entryId}/index.json`, JSON.stringify(refused));

      openMemberPage(entryId, language);
      await expectNotAvailable(language, reason);
    });
  });

  it("would notice a page that cannot draw a member's decision or squad", async () => {
    // A check that has only ever seen good documents proves nothing about its own
    // sensitivity. Break a real member's plan, then its squad, and require a failure.
    const entryId = humans[0]!;
    const index = readPublished<LeagueViewEnvelope<EntryAdviceIndex>>(
      `${LEAGUE}/advice/${entryId}/index.json`,
    ).payload;
    const squad = readPublished<LeagueViewEnvelope<EntrySquad>>(
      `${LEAGUE}/entries/${entryId}.json`,
    );
    const selection = resolvePublishedAdvice(
      new URLSearchParams(),
      squad.payload.league_id,
      entryId,
      league!.members,
      index,
      { season: squad.payload.season, gameweek: squad.payload.gameweek },
    );
    const plan = readPublished<LeagueViewEnvelope<EntryAdvice>>(`${LEAGUE}/${selection.path!}`);
    overrides.set(
      `${LEAGUE}/${selection.path!}`,
      JSON.stringify({ ...plan, payload: { ...plan.payload, moves: null } }),
    );
    await expect(expectMemberDrawn(entryId, "en")).rejects.toThrow();

    cleanup();
    overrides.clear();
    overrides.set(
      `${LEAGUE}/entries/${entryId}.json`,
      JSON.stringify({ ...squad, payload: { ...squad.payload, starting_xi: null } }),
    );
    openMemberPage(entryId, "en");
    const copy = MESSAGES.en.leagueMembers;
    expect(await screen.findByText(copy.entryUnreadable, undefined, WAIT)).toBeInTheDocument();
    expect(() => expectNoFailure("en")).toThrow();
  });
});
