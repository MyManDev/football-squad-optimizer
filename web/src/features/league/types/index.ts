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
  /** The week **gross** of the transfer hit, as the source states it. */
  gameweek_points: number | null;
  /**
   * The hit taken that week, so the gross week above can be netted.
   *
   * Null is a claim, not a zero: it says nothing proves this row's hit. A row whose hit
   * is null therefore shows no gameweek score at all, rather than a gross number in a
   * column that reads as net.
   */
  transfer_cost: number | null;
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

/** The halves a chip's windows belong to; the 2026-27 season lists each chip once per half. */
export type ChipHalf = "first_half" | "second_half";

/**
 * One published window of one chip, as the member stands before `chips.gameweek`:
 * `used` (with `gameweek` the week it was played), `expired` (closed unplayed), `not_yet`
 * (not open yet), `available`, or `unknown` when the member's chip history was not
 * captured at all. No history is not the same thing as no chips played.
 */
export type ChipWindowStateName = "used" | "expired" | "not_yet" | "available" | "unknown";

export interface ChipWindowState {
  state: ChipWindowStateName;
  gameweek: number | null;
  start_event: number;
  stop_event: number;
}

/**
 * What the member can still play, by chip and half, read before the upcoming deadline.
 * Read `known` first: when it is false every window is `unknown` and `chips_used` is
 * null, because the producer had no history to read. A chip the season lists once
 * carries null for its second half.
 */
export interface EntryChipAvailability {
  known: boolean;
  gameweek: number;
  states: Record<string, Record<ChipHalf, ChipWindowState | null>>;
}

/**
 * A player in a member's published fifteen: the shared view plus the armband the capture
 * recorded for him.
 */
export interface EntrySquadPlayer extends PlayerView {
  /**
   * True for the one player the member's picks named vice-captain. Absent, never false,
   * on every record of a document whose source did not state a held vice, and on every
   * document published before the field: absent means "not stated", which is not the same
   * claim as "nobody holds it". It rides bench records too, because the platform lets the
   * armband sit on the bench.
   */
  is_vice_captain?: boolean;
}

export interface EntrySquad {
  league_id: number;
  season: string;
  gameweek: number;
  scored_gameweek: number | null;
  entry: HumanEntryView;
  starting_xi: EntrySquadPlayer[];
  bench: EntrySquadPlayer[];
  bank_tenths: number;
  free_transfers: number;
  free_transfers_known: boolean;
  /** Chip name to the gameweeks it was played; null when the history was not captured. */
  chips_used: Record<string, number[]> | null;
  /** Absent on documents from before the block. */
  chips?: EntryChipAvailability;
  purchase_prices_known: boolean;
  /**
   * What the fifteen would raise if they were all sold, in tenths, and that plus the
   * bank: what the member may spend at the coming deadline. Adding up the squad's current
   * prices does not give either number, because the game keeps half of every rise since a
   * player was bought, so the publisher states them rather than leaving a page to guess.
   * Absent on documents from before the pair; null where a source states neither.
   */
  squad_sell_value_tenths?: number | null;
  spendable_budget_tenths?: number | null;
  source_snapshot_id: string | null;
  squadopt_comparison: EntryScoreComparison | null;
  data_quality: EntryDataQuality;
  missing_fields: string[];
  /**
   * Which squad `starting_xi` and `bench` are: `captured` (the played week's own picks)
   * or `pre_free_hit_gwNN` when a Free Hit voided that week's fifteen and the page shows
   * the squad held before it. Absent on documents from before the field.
   */
  squad_basis?: string;
  /** The chip active in the captured week as the source reported it, or null. */
  active_chip?: string | null;
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

/**
 * One out/in swap, matched by pitch position so the row is a transfer the game accepts.
 * A move carries no cost of its own: the week's hit charge belongs to the week, not to
 * one swap, and travels on the payload as `transfer_hit_points`.
 */
export interface AdviceMove {
  move_id: string;
  player_out: AdvicePlayer | null;
  player_in: AdvicePlayer | null;
  expected_points_delta: number;
  reason_code: "window_value" | "mode_tradeoff" | "points_gain";
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
  /**
   * The declared rule's pick among the three strategies, and the two numbers it read:
   * the member's league points against their default rival (signed, negative when
   * behind) and the gameweeks still to be played, plus the band edge those were
   * compared against, so a reader can re-apply the rule instead of trusting it.
   *
   * It is a band on points and nothing else: no bench has compared a member who
   * follows it with one who ignores it, so the page labels it a declared rule rather
   * than an edge. `null` when the standings do not prove both totals; absent on an
   * index published before the rule existed.
   */
  suggested_strategy?: {
    strategy: MemberStrategy;
    rule_id: string;
    band: "behind" | "level" | "ahead";
    rival_entry_id: number;
    points_ahead_of_rival: number;
    scored_gameweek: number;
    gameweeks_remaining: number;
    band_edge_points: number;
  } | null;
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
   * The week's hit charge, once: the game takes four points for each transfer beyond
   * the free ones, and it charges the week rather than any one move. Absent on documents
   * published before the producer stated it here (they carried it on every move row).
   */
  transfer_hit_points?: number;
  /**
   * The whole plan's expected-points price against the pure-points pick — the only
   * cross-mode number the producer publishes (never a probability). Absent on documents
   * published before the competitive modes were computed.
   */
  expected_points_cost?: number;
  /**
   * The most that price can be. A price tag is a difference between two solved plans,
   * and it is the cost itself only when both proofs finished; when one did not, the
   * producer carries its solver's own bound onto the difference and publishes the
   * result here. Equal to `expected_points_cost` under a proof, never below it, never
   * below zero. Published on the rival strategies; absent on documents published before
   * the producer carried it, and on the modes priced by the scenario menu.
   */
  expected_points_cost_ceiling?: number;
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
    /** The same ceiling, for the candidate that was not taken. */
    expected_points_cost_ceiling?: number;
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
  /**
   * Which squad the advice stands on: `captured` (the played week's own picks) or
   * `pre_free_hit_gwNN` when a Free Hit voided that week's fifteen and the advice
   * was built on the squad held before it. Absent on documents from before the field.
   */
  squad_basis?: string;
}

/**
 * The weekly scoreboard (`data/league/scoreboard.json`), written by
 * `scripts/build_scoreboard.py` from one live capture, the registry, the ledger and an
 * optional Top-100 capture. Every field is what a file on disk says; `null` is "the file
 * does not say", never a zero standing in for an absence.
 */
export interface ScoreboardOurs {
  /** The ledger's settled net (named eleven, captain, chip, minus hits); null until settled. */
  net: number | null;
  xi: number | null;
  hits: number;
  projected: number;
  /** `live`: decided before the deadline; `replay`: recorded afterwards from a pre-deadline capture. */
  mode: "live" | "replay" | null;
  /** Legacy named-eleven scoring or settlement using a recorded bench order and vice. */
  scoring_basis: "named_eleven_no_autosubs" | "official_autosub_captain_v2";
  vice_captain_named: boolean;
  diagnostics?: ScoreboardDiagnostics;
  outcome_snapshot_id?: string | null;
}

export interface ScoreboardTop100 {
  gameweek: number;
  /**
   * The cohort's mean week on the basis `basis` names: `net` is the mean of each member's
   * own `points - event_transfers_cost`, the same basis as the members' and our columns;
   * `gross` is the mean of the standings' `event_total`, which is before the transfer
   * cost and therefore not comparable with them.
   */
  mean_score: number;
  basis: "net" | "gross";
  /** The transfer cost taken off across the cohort; null when the mean is gross. */
  hit_points: number | null;
  /** The elite-picks capture the net was read from; null when the mean is gross. */
  picks_snapshot_id: string | null;
  cohort_size: number;
  /** True only when that gameweek was finished and checked in the cohort capture's bootstrap. */
  final: boolean;
}

export interface ScoreboardMember {
  entry_id: number;
  /** Gross, as the member's history publishes it. */
  points: number;
  hit_cost: number | null;
  /** `points - hit_cost`: the same net our ledger records. Null when the cost is unknown. */
  net: number | null;
  total_points: number;
}

export interface ScoreboardGameweek {
  gameweek: number;
  deadline_utc: string;
  finished: boolean;
  data_checked: boolean;
  average_entry_score: number | null;
  highest_score: number | null;
  ours: ScoreboardOurs | null;
  top100: ScoreboardTop100 | null;
  members: ScoreboardMember[];
  members_mean_net: number | null;
  members_counted: number;
  /** Additive extension; absent on older publications. */
  comparisons?: ScoreboardComparison[];
}

export interface ScoreboardCumulative {
  through_gameweek: number | null;
  gameweeks: number[];
  ours_net: number | null;
  /** The gameweeks `ours_net` covers; a subset of `gameweeks` until the ledger catches up. */
  ours_gameweeks: number[];
  members_mean_total_points: number | null;
  /**
   * The gameweeks `members_mean_total_points` covers. It is a running total at
   * `through_gameweek`, so it spans every week played up to it, finished or not — a
   * superset of `gameweeks` whenever the finished weeks run with a gap.
   */
  members_gameweeks: number[];
  members_counted: number;
  average_entry_score: number | null;
}

export interface Scoreboard {
  season: string;
  league_id: number;
  source_snapshot_id: string;
  captured_at_utc: string;
  cohort_snapshot_id: string | null;
  /** The elite-picks capture the builder was handed, whether or not it netted the cohort. */
  cohort_picks_snapshot_id: string | null;
  registered_members: number;
  histories_held: number;
  gameweeks: ScoreboardGameweek[];
  cumulative: ScoreboardCumulative;
}

export interface ScoreboardDiagnostics {
  zero_minute_starters: number | null;
  minutes_shortfall: number | null;
  captain_shortfall: number | null;
  autosub_recovery: number | null;
}

export interface ScoreboardComparison {
  kind: "system" | "base" | "elite_xi" | "ownership_template" | "league_mean" | "game_mean";
  net: number | null;
  scoring_basis: string | null;
  source_snapshot_id: string | null;
  diagnostics: ScoreboardDiagnostics;
}
