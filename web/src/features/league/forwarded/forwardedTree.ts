/**
 * The tree of a league the site does not publish, read as the published trees are but built
 * on the device from the FPL forwarder's documents (#983 step 4): the member list from the
 * standings pages read, each member's squad from their bundle and the capture's table, and
 * a device-menu index for each, so the member page's shared hooks (`useLeagueMemberData`,
 * `useDevicePlan`, `useMemberLiveScore`) read a forwarded league exactly as they read a
 * published one. The scoreboard and each member's history are built from the members'
 * seasons and the game's events (`forwardedScoreboard`). Nothing is solved ahead for such a
 * league, so every advice document still reads as not published.
 */

import type { RequestOptions } from "../../../data/request";
import type { FixturesPayload } from "../../fixtures/types";
import { LeagueDataError, LeagueDataMissing, type LeagueTree } from "../data";
import type { PublishedLeague } from "../directory";
import { fetchPublishedJson } from "../publishedJson";
import { RIVAL_STRATEGIES, type DevicePlanDocument } from "../device/types";
import {
  entryBundle as readBundle,
  entrySeason as readSeason,
  events as readEvents,
  standings as readStandings,
} from "../forwarder/client";
import type { ForwarderClient } from "../forwarder/client";
import type {
  FplEntryBundle,
  FplEntrySeason,
  FplLeagueStandings,
  FplStandingRow,
} from "../forwarder/documents";
import { forwardedHistory, forwardedScoreboard } from "./forwardedScoreboard";
import { assertAdviceIndex, assertMembers } from "../publicationShape";
import type {
  EntryAdviceIndex,
  EntryChipAvailability,
  EntrySquad,
  EntryView,
  LeagueMembers,
  LeagueViewEnvelope,
  RankMovement,
  Scoreboard,
} from "../types";
import { forwardedMemberSquad } from "./memberSquad";

/** The forwarder reads the tree makes; the site's own unless a test injects them. */
export interface ForwardedSources {
  standings: ForwarderClient["standings"];
  entryBundle: ForwarderClient["entryBundle"];
  entrySeason: ForwarderClient["entrySeason"];
  events: ForwarderClient["events"];
}

export interface ForwardedTreeInputs {
  /** The league the page was opened from, or league 0 for an entry opened on its own. */
  league: PublishedLeague;
  /** The capture's own table the page read; every squad and index names its capture. */
  table: LeagueViewEnvelope<DevicePlanDocument>;
  /** The site's calendar, for the purchase-price replay of each squad. */
  fixtures: FixturesPayload | null;
  /** The standings pages already read, so the tree reads none of them twice. */
  pages?: readonly FplLeagueStandings[];
  /** The bundles already read, the member's own among them. */
  bundles?: readonly FplEntryBundle[];
  sources?: ForwardedSources;
}

const SITE_SOURCES: ForwardedSources = {
  standings: readStandings,
  entryBundle: readBundle,
  entrySeason: readSeason,
  events: readEvents,
};

/** The movement a standings row states, in the member list's words and under its rule. */
function movementOf(row: FplStandingRow): Pick<EntryView, "movement" | "movement_places"> {
  if (row.rank <= 0) return { movement: "unknown", movement_places: null };
  if (row.last_rank === null || row.last_rank <= 0) {
    return { movement: "new", movement_places: null };
  }
  const places = Math.abs(row.last_rank - row.rank);
  const movement: RankMovement = places === 0 ? "same" : row.rank < row.last_rank ? "up" : "down";
  return { movement, movement_places: places };
}

/**
 * The standings rows as the member list's rows: the week's gross from `event_total` with no
 * hit stated (so no week score is shown, as the list's rule reads a null hit), the total
 * and the movement the standings state. A row repeated across pages keeps its first copy.
 */
export function standingsMembers(pages: readonly FplLeagueStandings[]): EntryView[] {
  const seen = new Set<number>();
  const members: EntryView[] = [];
  for (const page of pages) {
    for (const row of page.results) {
      if (seen.has(row.entry)) continue;
      seen.add(row.entry);
      members.push({
        member_kind: "human",
        entry_id: row.entry,
        manager_name: row.player_name,
        team_name: row.entry_name,
        rank: row.rank,
        gameweek_points: row.event_total,
        transfer_cost: null,
        total_points: row.total,
        ...movementOf(row),
        data_quality: "partial",
      });
    }
  }
  return members.sort((a, b) => a.rank - b.rank);
}

/** The rival a published index names first: the member ranked just above, else just below. */
export function defaultRivalOf(members: readonly EntryView[], entryId: number): number | null {
  const own = members.find((member) => member.entry_id === entryId);
  if (own === undefined) return null;
  const others = members.filter(
    (member): member is Extract<EntryView, { member_kind: "human" }> =>
      member.member_kind === "human" && member.entry_id !== entryId,
  );
  const above = others.filter((member) => member.rank < own.rank).sort((a, b) => b.rank - a.rank);
  const below = others.filter((member) => member.rank >= own.rank).sort((a, b) => a.rank - b.rank);
  return above[0]?.entry_id ?? below[0]?.entry_id ?? null;
}

/** The index's chip states: the squad's block, or none known where the table lists no windows. */
function chipStates(squad: EntrySquad, gameweek: number): EntryChipAvailability {
  return squad.chips ?? { known: false, gameweek, states: {} };
}

/**
 * The forwarded league's tree. Each member's bundle is read once per tree, for the table's
 * gameweek, and bound to the table by the identity rule; a member the rule refuses reads as
 * not published, a read the forwarder could not answer as an error, so a rival the page
 * cannot use is left out while a rival it could not reach is named as unread.
 */
export function forwardedTree({
  league,
  table,
  fixtures,
  pages = [],
  bundles = [],
  sources = SITE_SOURCES,
}: ForwardedTreeInputs): LeagueTree {
  const unpublished = (relative: string) => () => Promise.reject(new LeagueDataMissing(relative));
  const gameweek = table.payload.gameweek;
  const standingsPages: FplLeagueStandings[] = [...pages];
  const squads = new Map<number, Promise<LeagueViewEnvelope<EntrySquad>>>();
  const seasons = new Map<number, Promise<FplEntrySeason | null>>();
  let board: Promise<LeagueViewEnvelope<Scoreboard>> | null = null;
  let firstPage: Promise<FplLeagueStandings> | null = null;

  function standingOf(entryId: number): FplStandingRow | null {
    for (const page of standingsPages) {
      const row = page.results.find((result) => result.entry === entryId);
      if (row !== undefined) return row;
    }
    return null;
  }

  function build(entryId: number, bundle: FplEntryBundle): LeagueViewEnvelope<EntrySquad> {
    const built = forwardedMemberSquad({
      bundle,
      table,
      entryId,
      fixtures,
      leagueId: league.leagueId,
      standing: standingOf(entryId),
    });
    if (built.ok) return built.squad;
    if (built.reason === "unreadable" || built.reason === "table_unreadable") {
      throw new LeagueDataError(`The squad of ${entryId} could not be read: ${built.reason}.`);
    }
    throw new LeagueDataMissing(`entries/${entryId}.json`);
  }

  for (const bundle of bundles) {
    if (bundle.gameweek !== gameweek) continue;
    squads.set(
      bundle.entry_id,
      new Promise((resolve, reject) => {
        try {
          resolve(build(bundle.entry_id, bundle));
        } catch (error) {
          reject(error as Error);
        }
      }),
    );
  }

  /** The pages handed in, else page 1 read once; a standalone entry has no league to read. */
  async function knownPages(): Promise<readonly FplLeagueStandings[]> {
    if (standingsPages.length > 0 || league.leagueId <= 0) return standingsPages;
    firstPage ??= sources.standings(league.leagueId, 1).then((read) => {
      if (!read.ok) throw new LeagueDataError(`The standings could not be read: ${read.reason}.`);
      standingsPages.push(read.document);
      return read.document;
    });
    await firstPage;
    return standingsPages;
  }

  async function members(): Promise<LeagueViewEnvelope<LeagueMembers>> {
    if (league.leagueId <= 0) throw new LeagueDataMissing("members.json");
    const read = await knownPages();
    return assertMembers({
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: read[0]?.source_time ?? table.generated_at_utc,
      source_kind: "live",
      payload: {
        league_id: league.leagueId,
        league_name: league.leagueName || (read[0]?.league.name ?? ""),
        season: table.payload.season,
        gameweek,
        public_after_deadline: true,
        scored_gameweek: null,
        members: standingsMembers(read),
      },
    });
  }

  function entrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>> {
    let squad = squads.get(entryId);
    if (squad === undefined) {
      squad = sources.entryBundle(entryId, gameweek).then((read) => {
        if (read.ok) return build(entryId, read.document);
        if (read.reason === "entry_not_found" || read.reason === "not_found") {
          throw new LeagueDataMissing(`entries/${entryId}.json`);
        }
        throw new LeagueDataError(`The bundle of ${entryId} could not be read: ${read.reason}.`);
      });
      squads.set(entryId, squad);
    }
    return squad;
  }

  async function entryAdviceIndex(entryId: number): Promise<LeagueViewEnvelope<EntryAdviceIndex>> {
    const [squad, list] = await Promise.all([
      entrySquad(entryId),
      league.leagueId > 0 ? members() : null,
    ]);
    const roster = list?.payload.members ?? [];
    const rivals = roster
      .map((member) => member.entry_id)
      .filter((id): id is number => id !== null && id !== entryId);
    const index: EntryAdviceIndex = {
      menu: "device",
      source_snapshot_id: table.payload.source_snapshot_id,
      chip_states: chipStates(squad.payload, gameweek),
      league_id: league.leagueId,
      season: table.payload.season,
      gameweek,
      entry_id: entryId,
      window: 1,
      windows: Object.fromEntries(["saf-puan", ...RIVAL_STRATEGIES].map((slug) => [slug, []])),
      strategies: ["saf-puan", ...RIVAL_STRATEGIES],
      rival_entry_ids: rivals,
      default_rival_entry_id: defaultRivalOf(roster, entryId),
      evidence: { available: false, reason: "on_device" },
      top100: { available: false, reason: "on_device" },
      chips: { available: false, reason: "on_device" },
      suggested_strategy: null,
      computed: [],
      unavailable: [],
    };
    const envelope: LeagueViewEnvelope<EntryAdviceIndex> = {
      contract_version: "provisional_league_ui_v1",
      generated_at_utc: squad.generated_at_utc,
      source_kind: "live",
      payload: index,
    };
    // A standalone entry's index names league 0, which the published shape refuses; the
    // page reads such an index for its menu only, so it is handed back unchecked.
    return league.leagueId > 0 ? assertAdviceIndex(envelope, entryId) : envelope;
  }

  return {
    league,
    async devicePlan(capture) {
      if (capture !== table.payload.source_snapshot_id) {
        throw new LeagueDataMissing(`device/${capture}/device-plan.json`);
      }
      return table;
    },
    members,
    entrySquad,
    entryAdvice: unpublished("advice"),
    entryAdviceEvidence: unpublished("advice"),
    entryAdviceChip: unpublished("advice"),
    entryAdviceTop100: unpublished("advice"),
    entryAdviceIndex,
    scoreboard,
    raw,
  };

  /** One member's season, read once per tree; a team FPL does not have reads as none. */
  function seasonOf(entryId: number): Promise<FplEntrySeason | null> {
    let season = seasons.get(entryId);
    if (season === undefined) {
      season = sources.entrySeason(entryId).then((read) => {
        if (read.ok) return read.document;
        if (read.reason === "entry_not_found" || read.reason === "not_found") return null;
        throw new LeagueDataError(`The season of ${entryId} could not be read: ${read.reason}.`);
      });
      seasons.set(entryId, season);
    }
    return season;
  }

  /**
   * The scoreboard, from the members the pages name: each one's season and the game's
   * events, read once per tree. A league with no page read yet reads page 1 first.
   */
  async function scoreboard(): Promise<LeagueViewEnvelope<Scoreboard>> {
    if (league.leagueId <= 0) throw new LeagueDataMissing("scoreboard.json");
    board ??= (async () => {
      const pages = await knownPages();
      const members = pages.flatMap((page) => page.results);
      const [calendar, read] = await Promise.all([
        sources.events(),
        Promise.all(members.map((member) => seasonOf(member.entry))),
      ]);
      if (!calendar.ok) {
        throw new LeagueDataError(`The game's events could not be read: ${calendar.reason}.`);
      }
      const answered = new Map<number, FplEntrySeason>();
      members.forEach((member, index) => {
        const season = read[index];
        if (season !== null && season !== undefined) answered.set(member.entry, season);
      });
      return forwardedScoreboard({
        leagueId: league.leagueId,
        table,
        members,
        seasons: answered,
        events: calendar.document,
        fixtures,
      });
    })();
    return board;
  }

  /** The member histories; the requested history and every other document stay unpublished. */
  async function raw(relative: string, options?: RequestOptions): Promise<unknown> {
    if (league.leagueId <= 0) throw new LeagueDataMissing(relative);
    // What the member asked the service for, as the weekly run publishes it for public
    // teams beside the listed leagues' trees: data/public/<league>/history/requested/<id>.json.
    const requested = /^history\/requested\/([1-9][0-9]*)\.json$/.exec(relative);
    if (requested !== null) {
      return fetchPublishedJson(
        `${import.meta.env.BASE_URL}data/`,
        `public/${league.leagueId}/${relative}`,
        options,
      );
    }
    const match = /^history\/([1-9][0-9]*)\.json$/.exec(relative);
    if (match === null) throw new LeagueDataMissing(relative);
    const season = await seasonOf(Number(match[1]));
    if (season === null) throw new LeagueDataMissing(relative);
    return forwardedHistory({ leagueId: league.leagueId, table, season, fixtures });
  }
}
