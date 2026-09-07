import type { PlayerView } from "../../../data/schema";
import type { PlayMode, WindowSize } from "../../moves/modePrices";

/**
 * The strategies the producer computes for a league member: the catalogue's computable
 * ones. `saf-puan` is rival-free; the other two are solved against a named rival, and
 * the producer publishes one file per (strategy, rival) plus an index.
 */
export const MEMBER_STRATEGIES = ["saf-puan", "ortak-koru", "fark-yarat"] as const;
export type MemberStrategy = (typeof MEMBER_STRATEGIES)[number];

export function isMemberStrategy(value: unknown): value is MemberStrategy {
  return MEMBER_STRATEGIES.some((slug) => slug === value);
}

export function strategyNeedsRival(strategy: string): boolean {
  return strategy === "ortak-koru" || strategy === "fark-yarat";
}

/** A strategy a request may name: a member strategy, or a legacy play mode. */
export type AdviceStrategy = PlayMode | MemberStrategy;

// Provisional: until these types move to docs/contracts, this file—not İbo's #127
// schema—is the source of truth for the mock-first league UI.
export interface LeagueViewEnvelope<T> {
  contract_version: "provisional_league_ui_v1";
  generated_at_utc: string;
  source_kind: "example" | "live";
  payload: T;
}

export type EntryDataQuality = "complete" | "partial" | "empty";
export type RankMovement = "up" | "down" | "same" | "new" | "unknown";

interface EntryStanding {
  manager_name: string | null;
  team_name: string | null;
  rank: number;
  gameweek_points: number | null;
  total_points: number | null;
  movement: RankMovement;
  movement_places: number | null;
  data_quality: EntryDataQuality;
}

export type EntryView =
  | (EntryStanding & {
      member_kind: "human";
      entry_id: number;
    })
  | (EntryStanding & {
      member_kind: "system";
      entry_id: null;
    });

export type HumanEntryView = Extract<EntryView, { member_kind: "human" }>;

export interface LeagueMembers {
  league_id: number;
  league_name: string;
  season: string;
  gameweek: number;
  public_after_deadline: boolean;
  /** The gameweek the members' points were scored in; null while none is final. */
  scored_gameweek: number | null;
  members: EntryView[];
}

export interface EntrySquad {
  league_id: number;
  season: string;
  gameweek: number;
  scored_gameweek: number | null;
  entry: HumanEntryView;
  starting_xi: PlayerView[];
  bench: PlayerView[];
  bank_tenths: number;
  free_transfers: number;
  free_transfers_known: boolean;
  chips_used: Record<string, number[]>;
  purchase_prices_known: boolean;
  source_snapshot_id: string | null;
  squadopt_comparison: EntryScoreComparison | null;
  data_quality: EntryDataQuality;
  missing_fields: string[];
}

export interface EntryScoreComparison {
  member_gameweek_points: number;
  squadopt_gameweek_points: number;
  difference_points: number;
}

export interface AdvicePlayer {
  player_id: number;
  name: string;
  short_name: string;
  position: PlayerView["position"];
  team: string;
  /** Present on lineup players: the projection's expected points for the gameweek. */
  expected_points?: number;
}

/** The chips the producer's planner models; the payload names the one it plays, if any. */
export type AdviceChip = "bboost" | "3xc" | "wildcard" | "freehit";

export interface AdviceMove {
  move_id: string;
  player_out: AdvicePlayer | null;
  player_in: AdvicePlayer | null;
  expected_points_delta: number;
  expected_points_cost: number;
  reason_code: "window_value" | "mode_tradeoff";
}

/** What the producer computed for one member, and what it could not, with the reason. */
export interface EntryAdviceIndex {
  league_id: number;
  season: string;
  gameweek: number;
  entry_id: number;
  window: WindowSize;
  /**
   * Per strategy, the windows whose file the producer wrote: pure points at one, three
   * and five weeks where each solved, every rival strategy at one week. Absent on an
   * index from before the windows existed, which means window one only.
   */
  windows?: Partial<Record<string, WindowSize[]>>;
  strategies: string[];
  rival_entry_ids: number[];
  default_rival_entry_id: number | null;
  computed: { strategy: string; rival_entry_id: number; path: string }[];
  /**
   * A (strategy, rival) pair with no plan, or — with `rival_entry_id` null and the
   * `window` named — a pure-points window that did not solve, each with its reason.
   */
  unavailable: {
    strategy: string;
    rival_entry_id: number | null;
    window?: WindowSize;
    reason: string;
  }[];
}

/**
 * One gameweek of a three- or five-week plan: the transfers it makes, the hit points
 * it pays, the chip it plays, the free transfers around it and the planner's expected
 * points for that week's eleven (captain doubled, before hits).
 */
export interface AdvicePlanWeek {
  gameweek: number;
  transfers_in: AdvicePlayer[];
  transfers_out: AdvicePlayer[];
  transfer_hit_points: number;
  chip: AdviceChip | null;
  free_transfers_before: number;
  free_transfers_after: number;
  expected_points: number;
}

export interface EntryAdvice {
  league_id: number;
  season: string;
  gameweek: number;
  entry_id: number;
  mode: AdviceStrategy;
  window: WindowSize;
  source_snapshot_id: string | null;
  moves: AdviceMove[];
  /**
   * The whole plan's expected-points price against the pure-points pick — the only
   * cross-mode number the producer publishes (never a probability). Absent on documents
   * published before the competitive modes were computed.
   */
  expected_points_cost?: number;
  /** The league neighbour the competitive modes were priced against; null for saf-puan. */
  rival_label?: string | null;
  /**
   * The solver's own account of the plan: "OPTIMAL" is a proof, "FEASIBLE" is a found
   * plan whose proof did not finish inside the budget. Absent on documents published
   * before the producer carried it.
   */
  solver_status?: string | null;
  /** The measured bound gap beside a FEASIBLE plan; 0 under proof. */
  optimality_gap?: number | null;
  /** Rival strategies: the rival the plan was priced against and the set arithmetic. */
  rival_entry_id?: number;
  overlap_count?: number;
  expected_gap_vs_rival?: number;
  captain_agreement?: boolean;
  /** The control the price tag anchors on, with its own proof status and bound gap. */
  control_solver_status?: string | null;
  control_optimality_gap?: number | null;
  /**
   * The transfer rule the strategy played under: the free transfers it could spend
   * without hits, the overlap it asked for, the overlap it applied, and which of the
   * two candidates won — within the free transfers, or the target with hits. The
   * other candidate travels as the alternative with its own price.
   */
  transfer_cap?: number;
  overlap_target?: number;
  overlap_applied?: number;
  plan_kind?: "within_free_transfers" | "with_hits";
  alternative_plan?: {
    kind: "within_free_transfers" | "with_hits";
    overlap_applied: number;
    transfer_hit_points: number | null;
    expected_points_cost: number;
  } | null;
  /**
   * The rest of the decision, published since the producer carried the plan's first
   * week: the eleven plus the captain's double in expected points, the armband, the
   * eleven in pitch order, the bench in the order the game's autosubs walk it, and the
   * chip. Null on a decision handed over without its plan week; absent on documents
   * published before the producer carried them.
   */
  expected_own_points?: number | null;
  captain?: AdvicePlayer | null;
  vice_captain?: AdvicePlayer | null;
  starting_xi?: AdvicePlayer[] | null;
  bench?: AdvicePlayer[] | null;
  chip?: AdviceChip | null;
  /**
   * A three- or five-week window: one row per gameweek, and the sentences the
   * producer states about what the window assumes (the first week's projection
   * repeated over the fixture calendar, among others). The moves and the lineup
   * above are the first week's. Absent on one-week documents.
   */
  plan_weeks?: AdvicePlanWeek[] | null;
  stated_limits?: string[] | null;
  data_quality: EntryDataQuality;
  missing_fields: string[];
}
