/**
 * The data boundary of the frontend.
 *
 * Every page reads through `DataClient`; today the static client fetches the JSON tree
 * `squadopt.application.build_site` wrote under `data/`, later an API client can serve
 * the same view models. Payloads whose contract version is not the one this build was
 * generated for are refused: the page shows why instead of rendering the wrong shape.
 */

import type {
  LeagueView,
  LedgerView,
  PoolView,
  RecommendationView,
  SiteIndex,
  StatusView,
} from "./schema";
import { readLiveScore, type LiveScoreView } from "./liveScore";

export const UI_VIEW_CONTRACT_VERSION = "ui_view_v1";

export interface ViewEnvelope<T> {
  contract_version: string;
  generated_at_utc: string;
  payload: T;
}

export interface Loaded<T> {
  payload: T;
  generatedAtUtc: string;
}

export interface DataClient {
  getLiveScore?(season: string, gameweek: number): Promise<Loaded<LiveScoreView>>;
  getIndex(): Promise<Loaded<SiteIndex>>;
  getRecommendation(season: string, gameweek: number): Promise<Loaded<RecommendationView>>;
  getPool(season: string, gameweek: number): Promise<Loaded<PoolView>>;
  getLedger(season: string): Promise<Loaded<LedgerView>>;
  getLeague(season: string): Promise<Loaded<LeagueView>>;
  getStatus(season: string): Promise<Loaded<StatusView>>;
}

export class ContractMismatchError extends Error {
  readonly found: string;
  readonly expected: string;
  constructor(found: string, expected: string) {
    super(`This page was built for ${expected}; the data says ${found}.`);
    this.name = "ContractMismatchError";
    this.found = found;
    this.expected = expected;
  }
}

export class NotFoundError extends Error {
  readonly path: string;
  constructor(path: string) {
    super(`No data at ${path}.`);
    this.name = "NotFoundError";
    this.path = path;
  }
}

export function gameweekPath(season: string, gameweek: number, file = "recommendation"): string {
  return `${season}/gw${String(gameweek).padStart(2, "0")}/${file}.json`;
}

function unwrap<T>(value: unknown): Loaded<T> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid published view envelope.");
  }
  const envelope = value as ViewEnvelope<T>;
  if (envelope.contract_version !== UI_VIEW_CONTRACT_VERSION) {
    throw new ContractMismatchError(envelope.contract_version, UI_VIEW_CONTRACT_VERSION);
  }
  if (
    envelope.payload === null ||
    typeof envelope.payload !== "object" ||
    Array.isArray(envelope.payload) ||
    typeof envelope.generated_at_utc !== "string"
  ) {
    throw new Error("Invalid published view payload.");
  }
  return { payload: envelope.payload, generatedAtUtc: envelope.generated_at_utc };
}

export class StaticDataClient implements DataClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = `${import.meta.env.BASE_URL}data/`) {
    this.baseUrl = baseUrl;
  }

  private async read<T>(relative: string): Promise<Loaded<T>> {
    const response = await fetch(`${this.baseUrl}${relative}`, { cache: "no-cache" });
    if (response.status === 404) throw new NotFoundError(relative);
    if (!response.ok) throw new Error(`Could not load ${relative} (${response.status}).`);
    return unwrap((await response.json()) as ViewEnvelope<T>);
  }

  getIndex(): Promise<Loaded<SiteIndex>> {
    return this.read<SiteIndex>("index.json");
  }

  async getLiveScore(season: string, gameweek: number): Promise<Loaded<LiveScoreView>> {
    const relative = gameweekPath(season, gameweek, "live");
    const response = await fetch(`${this.baseUrl}${relative}`, { cache: "no-cache" });
    if (response.status === 404) throw new NotFoundError(relative);
    if (!response.ok) throw new Error(`Could not load ${relative} (${response.status}).`);
    return readLiveScore(await response.json(), season, gameweek);
  }

  getRecommendation(season: string, gameweek: number): Promise<Loaded<RecommendationView>> {
    return this.read<RecommendationView>(gameweekPath(season, gameweek));
  }

  getPool(season: string, gameweek: number): Promise<Loaded<PoolView>> {
    return this.read<PoolView>(gameweekPath(season, gameweek, "pool"));
  }

  getLedger(season: string): Promise<Loaded<LedgerView>> {
    return this.read<LedgerView>(`${season}/ledger.json`);
  }

  getLeague(season: string): Promise<Loaded<LeagueView>> {
    return this.read<LeagueView>(`${season}/league.json`);
  }

  getStatus(season: string): Promise<Loaded<StatusView>> {
    return this.read<StatusView>(`${season}/status.json`);
  }
}
