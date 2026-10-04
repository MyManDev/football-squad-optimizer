import { withRequestDeadline, type RequestOptions } from "../../data/request";
import { LeagueDataError, LeagueDataMissing } from "./dataErrors";
import { findLeague, loadLeagueDirectory, type LeagueRef, type PublishedLeague } from "./directory";
import { assertAdviceIndex, assertEnvelope, assertMembers, assertSquad } from "./publicationShape";
import { chipPath, isMemberChip } from "./advice/chipChoice";
import { isDevicePlanDocument, type DevicePlanDocument } from "./device/types";
import { isTop100Weight, top100TargetPath, type Top100Target } from "./advice/top100";
import type { WindowSize } from "../../lib/decisionVocabulary";
import type {
  EntryAdvice,
  EntrySquad,
  LeagueMembers,
  LeagueViewEnvelope,
  AdviceStrategy,
  EntryAdviceIndex,
  Scoreboard,
} from "./types";

export { LeagueDataError, LeagueDataMissing } from "./dataErrors";

/**
 * One league's published tree, read through its own path. Every page reads through the
 * tree the league gate hands it, so no document of one league is ever read as another's.
 */
export interface LeagueTree {
  readonly league: LeagueRef;
  devicePlan(options?: RequestOptions): Promise<LeagueViewEnvelope<DevicePlanDocument>>;
  members(): Promise<LeagueViewEnvelope<LeagueMembers>>;
  entrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>>;
  entryAdvice(
    entryId: number,
    mode: AdviceStrategy,
    window: WindowSize,
    rivalEntryId?: number | null,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>>;
  entryAdviceEvidence(
    entryId: number,
    path: string,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>>;
  entryAdviceChip(
    entryId: number,
    path: string,
    chip: string,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>>;
  entryAdviceTop100(
    entryId: number,
    path: string,
    weight: number,
    word: boolean,
    options?: RequestOptions,
    target?: Top100Target,
  ): Promise<LeagueViewEnvelope<EntryAdvice>>;
  entryAdviceIndex(entryId: number): Promise<LeagueViewEnvelope<EntryAdviceIndex>>;
  scoreboard(): Promise<LeagueViewEnvelope<Scoreboard>>;
  /** A document outside the envelope shape, by its path under the tree: the history and the series. */
  raw(relative: string, options?: RequestOptions): Promise<unknown>;
}

async function fetchDocument(
  base: string,
  relative: string,
  options?: RequestOptions,
): Promise<unknown> {
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${base}${relative}`, { cache: "no-cache", signal });
    if (response.status === 404) throw new LeagueDataMissing(relative);
    if (!response.ok)
      throw new LeagueDataError(`League data is not available (${response.status}).`);
    // Static hosts can return their HTML app shell for an unpublished JSON path.
    // A broken JSON publication is unreadable and must not become an example fallback.
    const body = await response.text();
    try {
      return JSON.parse(body) as unknown;
    } catch {
      if (/^\s*(?:<!doctype\s+html\b|<html\b)/i.test(body)) {
        throw new LeagueDataMissing(relative);
      }
      throw new LeagueDataError(`The published league document at ${relative} is not valid JSON.`);
    }
  }, options);
}

/**
 * The example league is a development and test convenience. The guard is written so the
 * production build can prove the import unreachable: without it the fixture module was
 * emitted as a chunk no production page ever loads, and it still counted against the
 * bundle budget.
 */
async function mockModule() {
  if (!import.meta.env.DEV && import.meta.env.MODE !== "test") {
    throw new Error("Example league data is not bundled in production.");
  }
  return import("../../fixtures/league");
}

export function createLeagueTree(league: LeagueRef): LeagueTree {
  const base = `${import.meta.env.BASE_URL}data/${league.path}/`;
  async function read<T>(
    relative: string,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<T>> {
    return assertEnvelope((await fetchDocument(base, relative, options)) as LeagueViewEnvelope<T>);
  }

  /**
   * Read the published document; fall back to the example one only in development, and only
   * when nothing is published.
   *
   * The gate used to be "development means examples", which was right while no league had
   * ever been published and wrong the day one was: a developer looking at the site saw a
   * league that does not exist, with players nobody owns, and had no way to reach the real
   * one short of a production build. Every disagreement between the producer and this side
   * (the file layout, the id space, our own missing row) survived because the surface a
   * developer actually looks at was showing fiction.
   *
   * Tests keep the examples unconditionally: they assert against fixture contents, and a
   * suite whose expectations depend on whether someone has run the producer locally is a
   * suite that fails for reasons unrelated to the change under test.
   */
  async function readOrExample<T>(
    relative: string,
    example: () => Promise<LeagueViewEnvelope<T>>,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<T>> {
    options?.signal?.throwIfAborted();
    if (import.meta.env.MODE === "test") return example();
    if (!import.meta.env.DEV) return read<T>(relative, options);
    try {
      return await read<T>(relative, options);
    } catch (error) {
      if (error instanceof LeagueDataMissing) return example();
      throw error;
    }
  }

  /**
   * The capture's table and rules for a solve on the member's own device. Published beside
   * members.json by the same build; absent on a tree from before it, which reads as
   * `LeagueDataMissing`. There is no example document: the page offers the device solve
   * only where the publisher wrote its inputs.
   */
  async function loadDevicePlan(
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<DevicePlanDocument>> {
    const envelope = await read<unknown>("device-plan.json", options);
    if (!isDevicePlanDocument(envelope.payload)) {
      throw new LeagueDataError("The published device-plan document is not the expected shape.");
    }
    return envelope as LeagueViewEnvelope<DevicePlanDocument>;
  }

  async function loadLeagueMembers(): Promise<LeagueViewEnvelope<LeagueMembers>> {
    return assertMembers(
      await readOrExample<LeagueMembers>(
        "members.json",
        async () => (await mockModule()).mockLeagueMembersEnvelope,
      ),
    );
  }

  async function loadEntrySquad(entryId: number): Promise<LeagueViewEnvelope<EntrySquad>> {
    return assertSquad(
      await readOrExample<EntrySquad>(`entries/${entryId}.json`, async () => {
        const fixture = (await mockModule()).mockEntrySquadEnvelopes[entryId];
        if (!fixture) throw new LeagueDataError(`No example entry ${entryId}.`);
        return fixture;
      }),
      entryId,
    );
  }

  async function loadEntryAdvice(
    entryId: number,
    mode: AdviceStrategy,
    window: WindowSize,
    rivalEntryId: number | null = null,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>> {
    // A named rival reads the producer's per-rival file; without one, the plain path:
    // the baseline for saf-puan, the standings neighbour's copy for a rival strategy.
    const relative =
      rivalEntryId === null
        ? `advice/${entryId}/${mode}/${window}.json`
        : `advice/${entryId}/${mode}/${window}/vs-${rivalEntryId}.json`;
    return readOrExample<EntryAdvice>(
      relative,
      async () => (await mockModule()).mockEntryAdviceEnvelope(entryId, mode, window, rivalEntryId),
      options,
    );
  }

  /**
   * The manager's-word plan, read only at the path an index may name for this member: the
   * one-week pure-points plan with the club's word switched on. Any other path is refused
   * rather than fetched, so a malformed index cannot point the page at another document.
   */
  async function loadEntryAdviceEvidence(
    entryId: number,
    path: string,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>> {
    const expected = `advice/${entryId}/saf-puan/1/hoca-sozu.json`;
    if (path !== expected) {
      throw new LeagueDataError(`The manager's-word plan for ${entryId} is not at ${path}.`);
    }
    return readOrExample<EntryAdvice>(
      expected,
      async () => (await mockModule()).mockEntryAdviceEvidenceEnvelope(entryId),
      options,
    );
  }

  /**
   * A Top 100 weighted plan, read only at the one path the producer writes for this member,
   * weight and switch. Any other path is refused rather than fetched, so a malformed index
   * cannot point the page at another document.
   */
  /** A chosen chip's document, read only from the one path such a document may live at. */
  async function loadEntryAdviceChip(
    entryId: number,
    path: string,
    chip: string,
    options?: RequestOptions,
  ): Promise<LeagueViewEnvelope<EntryAdvice>> {
    if (!isMemberChip(chip)) {
      throw new LeagueDataError(`No chip document exists for ${chip}.`);
    }
    const expected = chipPath(entryId, chip);
    if (path !== expected) {
      throw new LeagueDataError(`The ${chip} plan for ${entryId} is not at ${path}.`);
    }
    return readOrExample<EntryAdvice>(
      expected,
      async () => (await mockModule()).mockEntryAdviceChipEnvelope(entryId, chip),
      options,
    );
  }

  async function loadEntryAdviceTop100(
    entryId: number,
    path: string,
    weight: number,
    word: boolean,
    options?: RequestOptions,
    target: Top100Target = { strategy: "saf-puan", window: 1, rivalEntryId: null },
  ): Promise<LeagueViewEnvelope<EntryAdvice>> {
    if (!isTop100Weight(weight) || weight === 0) {
      throw new LeagueDataError(`No Top 100 document exists for setting ${weight}.`);
    }
    if (![1, 3, 5].includes(target.window) || !/^[a-z][a-z0-9-]{0,63}$/.test(target.strategy)) {
      throw new LeagueDataError("No Top 100 document exists for that plan.");
    }
    const expected = top100TargetPath(entryId, target, weight, word);
    if (expected === null || path !== expected) {
      throw new LeagueDataError(`The Top 100 plan for ${entryId} is not at ${path}.`);
    }
    return readOrExample<EntryAdvice>(
      expected,
      async () => (await mockModule()).mockEntryAdviceTop100Envelope(entryId, weight, word, target),
      options,
    );
  }

  async function loadEntryAdviceIndex(
    entryId: number,
  ): Promise<LeagueViewEnvelope<EntryAdviceIndex>> {
    const envelope = await readOrExample<EntryAdviceIndex>(
      `advice/${entryId}/index.json`,
      async () => (await mockModule()).mockEntryAdviceIndex(entryId),
    );
    return assertAdviceIndex(envelope, entryId);
  }

  /**
   * The weekly scoreboard has no example: it is a real-data surface, and a page that showed
   * an invented league table while nothing was published would be the fiction the example
   * gate above was narrowed to avoid. Missing arrives as `LeagueDataMissing`, and the page
   * says "not published yet".
   */
  async function loadScoreboard(): Promise<LeagueViewEnvelope<Scoreboard>> {
    const envelope = await read<Scoreboard>("scoreboard.json");
    if (!Array.isArray(envelope.payload?.gameweeks))
      throw new LeagueDataError("Missing scoreboard weeks.");
    for (const week of envelope.payload.gameweeks) {
      const rows = [week.ours, ...(week.comparisons ?? [])];
      for (const row of rows) {
        if (
          row?.net != null &&
          ![
            "named_eleven_no_autosubs",
            "official_autosub_captain_v2",
            "net",
            "source_average",
          ].includes(row.scoring_basis ?? "")
        ) {
          throw new LeagueDataError("A measured scoreboard row must name its scoring basis.");
        }
      }
    }
    return envelope;
  }

  return {
    league,
    devicePlan: loadDevicePlan,
    members: loadLeagueMembers,
    entrySquad: loadEntrySquad,
    entryAdvice: loadEntryAdvice,
    entryAdviceEvidence: loadEntryAdviceEvidence,
    entryAdviceChip: loadEntryAdviceChip,
    entryAdviceTop100: loadEntryAdviceTop100,
    entryAdviceIndex: loadEntryAdviceIndex,
    scoreboard: loadScoreboard,
    raw: (relative, options) => fetchDocument(base, relative, options),
  };
}

/**
 * The league a visitor named, if the site publishes it: its directory entry, read as the
 * publication the pages will read. A number the directory does not list is unsupported.
 */
export async function lookupPublishedLeague(
  leagueId: number,
): Promise<{ status: "connected"; league: PublishedLeague } | { status: "unsupported" }> {
  if (!Number.isSafeInteger(leagueId) || leagueId <= 0) {
    throw new LeagueDataError("A positive league ID is required.");
  }
  const directory = await loadLeagueDirectory();
  const league = findLeague(directory, leagueId);
  if (league === null) return { status: "unsupported" };
  const envelope = assertMembers(
    assertEnvelope(
      (await fetchDocument(
        `${import.meta.env.BASE_URL}data/${league.path}/`,
        "members.json",
      )) as LeagueViewEnvelope<LeagueMembers>,
    ),
  );
  const payload = envelope.payload;
  if (
    envelope.source_kind !== "live" ||
    !payload ||
    payload.league_id !== leagueId ||
    typeof payload.league_name !== "string" ||
    !payload.league_name.trim() ||
    typeof payload.season !== "string" ||
    !payload.season.trim() ||
    !Number.isSafeInteger(payload.gameweek) ||
    payload.gameweek <= 0 ||
    payload.public_after_deadline !== true ||
    !Array.isArray(payload.members) ||
    !payload.members.every(
      (member) =>
        member &&
        ((member.member_kind === "human" &&
          Number.isSafeInteger(member.entry_id) &&
          member.entry_id > 0) ||
          (member.member_kind === "system" && member.entry_id === null)),
    )
  ) {
    throw new LeagueDataError("The published public league record is invalid.");
  }
  return { status: "connected", league };
}
