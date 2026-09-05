import type { PlayerView } from "../../../data/schema";
import type { PlayMode, WindowSize } from "../../moves/modePrices";

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
}

export interface AdviceMove {
  move_id: string;
  player_out: AdvicePlayer | null;
  player_in: AdvicePlayer | null;
  expected_points_delta: number;
  expected_points_cost: number;
  reason_code: "window_value" | "mode_tradeoff";
}

export interface EntryAdvice {
  league_id: number;
  season: string;
  gameweek: number;
  entry_id: number;
  mode: PlayMode;
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
  data_quality: EntryDataQuality;
  missing_fields: string[];
}
