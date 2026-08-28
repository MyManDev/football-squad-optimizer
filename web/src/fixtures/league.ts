import type { PlayerView } from "../data/schema";
import type {
  AdviceMove,
  EntryAdvice,
  EntrySquad,
  EntryView,
  HumanEntryView,
  LeagueMembers,
  LeagueViewEnvelope,
} from "../features/league/types";
import type { PlayMode, WindowSize } from "../features/moves/modePrices";

const GENERATED_AT = "2026-08-22T04:00:00Z";
const LEAGUE_ID = 352490;
const SEASON = "2026-27";
const GAMEWEEK = 2;

function envelope<T>(payload: T): LeagueViewEnvelope<T> {
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: GENERATED_AT,
    source_kind: "example",
    payload,
  };
}

export const mockMembers: EntryView[] = [
  {
    entry_id: 35249001,
    member_kind: "human",
    manager_name: "Deniz Aral",
    team_name: "North Stand Notes",
    rank: 1,
    gameweek_points: 74,
    total_points: 132,
    movement: "up",
    movement_places: 2,
    data_quality: "complete",
  },
  {
    entry_id: 35249002,
    member_kind: "human",
    manager_name: "Mert Işık",
    team_name: "Half Space",
    rank: 2,
    gameweek_points: 68,
    total_points: 127,
    movement: "same",
    movement_places: 0,
    data_quality: "complete",
  },
  {
    entry_id: null,
    member_kind: "system",
    manager_name: "SquadOpt",
    team_name: "SquadOpt",
    rank: 3,
    gameweek_points: 65,
    total_points: 124,
    movement: "up",
    movement_places: 2,
    data_quality: "complete",
  },
  {
    entry_id: 35249003,
    member_kind: "human",
    manager_name: "Seda Kaya",
    team_name: "Late Flag FC",
    rank: 4,
    gameweek_points: 61,
    total_points: 119,
    movement: "down",
    movement_places: 1,
    data_quality: "complete",
  },
  {
    entry_id: 35249004,
    member_kind: "human",
    manager_name: "Arda Demir",
    team_name: "Expected Threat",
    rank: 5,
    gameweek_points: 59,
    total_points: 113,
    movement: "up",
    movement_places: 1,
    data_quality: "complete",
  },
  {
    entry_id: 35249005,
    member_kind: "human",
    manager_name: "Ece Uçar",
    team_name: "Bench Order",
    rank: 6,
    gameweek_points: 55,
    total_points: 109,
    movement: "down",
    movement_places: 1,
    data_quality: "complete",
  },
  {
    entry_id: 35249006,
    member_kind: "human",
    manager_name: "Can Ergin",
    team_name: "One More Fixture",
    rank: 7,
    gameweek_points: 52,
    total_points: 104,
    movement: "same",
    movement_places: 0,
    data_quality: "complete",
  },
  {
    entry_id: 35249007,
    member_kind: "human",
    manager_name: "İpek Aydın",
    team_name: "Low Block",
    rank: 8,
    gameweek_points: 49,
    total_points: 97,
    movement: "new",
    movement_places: null,
    data_quality: "complete",
  },
  {
    entry_id: 35249008,
    member_kind: "human",
    manager_name: "Bora Tan",
    team_name: "Clean Sheet Pending",
    rank: 9,
    gameweek_points: 44,
    total_points: 91,
    movement: "down",
    movement_places: 2,
    data_quality: "complete",
  },
  {
    entry_id: 35249009,
    member_kind: "human",
    manager_name: "Nil Öz",
    team_name: null,
    rank: 10,
    gameweek_points: null,
    total_points: 86,
    movement: "unknown",
    movement_places: null,
    data_quality: "partial",
  },
  {
    entry_id: 35249010,
    member_kind: "human",
    manager_name: null,
    team_name: "Awaiting Picks",
    rank: 11,
    gameweek_points: null,
    total_points: null,
    movement: "unknown",
    movement_places: null,
    data_quality: "empty",
  },
];

export const mockLeagueMembersEnvelope = envelope<LeagueMembers>({
  league_id: LEAGUE_ID,
  league_name: "SquadOpt Classic League",
  season: SEASON,
  gameweek: GAMEWEEK,
  public_after_deadline: true,
  scored_gameweek: GAMEWEEK - 1,
  members: mockMembers,
});

const playerPool = [
  [101, "Eren Vale", "Vale", "GK", "Northport", 50, 4.1],
  [116, "Ada Cove", "Cove", "GK", "Westborough", 45, 3.8],
  [117, "Theo Flint", "Flint", "GK", "Old Town", 40, 3.4],
  [102, "Jon Bell", "Bell", "DEF", "Riverside", 45, 4.4],
  [103, "Ari Stone", "Stone", "DEF", "Northport", 50, 4.7],
  [104, "Leon March", "March", "DEF", "Westborough", 55, 4.9],
  [118, "Nora Field", "Field", "DEF", "Cityside", 50, 4.3],
  [119, "Eli Brook", "Brook", "DEF", "East Dock", 45, 4.0],
  [120, "Ozan Reed", "O. Reed", "DEF", "Hill Athletic", 40, 3.7],
  [121, "Mina Ash", "Ash", "DEF", "Old Town", 40, 3.5],
  [105, "Mika Rowe", "Rowe", "MID", "Harbour", 75, 5.8],
  [106, "Samir Cole", "Cole", "MID", "Riverside", 80, 6.2],
  [107, "Emir Lane", "Lane", "MID", "Old Town", 95, 6.7],
  [108, "Noah Park", "Park", "MID", "Westborough", 65, 5.2],
  [122, "Derya West", "West", "MID", "Cityside", 70, 5.5],
  [123, "Luca Glen", "Glen", "MID", "East Dock", 55, 4.6],
  [124, "Maya King", "King", "MID", "Hill Athletic", 50, 4.2],
  [109, "Kai Reed", "Reed", "FWD", "Northport", 90, 6.5],
  [110, "Luis Hart", "Hart", "FWD", "Harbour", 75, 5.9],
  [111, "Owen Lake", "Lake", "FWD", "Old Town", 60, 4.8],
  [125, "Toni Wells", "Wells", "FWD", "Cityside", 70, 5.4],
  [126, "Ravi Ford", "Ford", "FWD", "East Dock", 65, 5.1],
] as const;

const FORMATIONS = [
  { DEF: 3, MID: 4, FWD: 3 },
  { DEF: 4, MID: 4, FWD: 2 },
  { DEF: 3, MID: 5, FWD: 2 },
  { DEF: 4, MID: 3, FWD: 3 },
  { DEF: 5, MID: 4, FWD: 1 },
] as const;

function selectPosition(
  position: PlayerView["position"],
  count: number,
  offset: number,
): PlayerView[] {
  const available = playerPool.filter(([, , , candidate]) => candidate === position);
  return Array.from(
    { length: count },
    (_, index) => available[(index + offset) % available.length]!,
  ).map(([id, name, shortName, selectedPosition, team, price, expected]) => ({
    player_id: id,
    name,
    short_name: shortName,
    position: selectedPosition,
    team,
    price_tenths: price,
    expected_points: expected,
    event_points: null,
    is_captain: false,
    bench_order: null,
    role: "starter",
  }));
}

function squadPlayers(entryOffset: number): { starting: PlayerView[]; bench: PlayerView[] } {
  const selected = {
    GK: selectPosition("GK", 2, entryOffset),
    DEF: selectPosition("DEF", 5, entryOffset),
    MID: selectPosition("MID", 5, entryOffset * 2),
    FWD: selectPosition("FWD", 3, entryOffset),
  };
  const formation = FORMATIONS[entryOffset % FORMATIONS.length]!;
  const starting = [
    ...selected.GK.slice(0, 1),
    ...selected.DEF.slice(0, formation.DEF),
    ...selected.MID.slice(0, formation.MID),
    ...selected.FWD.slice(0, formation.FWD),
  ];
  const captainId = starting.reduce((best, player) =>
    player.expected_points > best.expected_points ? player : best,
  ).player_id;
  const startingIds = new Set(starting.map((player) => player.player_id));
  const squad = [...selected.GK, ...selected.DEF, ...selected.MID, ...selected.FWD];

  return {
    starting: starting.map((player) => ({
      ...player,
      is_captain: player.player_id === captainId,
    })),
    bench: squad
      .filter((player) => !startingIds.has(player.player_id))
      .map((player, index) => ({
        ...player,
        role: "bench",
        bench_order: index + 1,
      })),
  };
}

function squadEnvelope(entry: HumanEntryView, index: number): LeagueViewEnvelope<EntrySquad> {
  const squadoptPoints = mockMembers.find(
    (member) => member.member_kind === "system",
  )?.gameweek_points;
  const squadoptComparison =
    entry.gameweek_points === null || squadoptPoints === null || squadoptPoints === undefined
      ? null
      : {
          member_gameweek_points: entry.gameweek_points,
          squadopt_gameweek_points: squadoptPoints,
          difference_points: entry.gameweek_points - squadoptPoints,
        };
  if (entry.data_quality === "empty") {
    return envelope({
      league_id: LEAGUE_ID,
      season: SEASON,
      gameweek: GAMEWEEK,
      scored_gameweek: GAMEWEEK - 1,
      entry,
      starting_xi: [],
      bench: [],
      bank_tenths: 0,
      free_transfers: 1,
      free_transfers_known: false,
      chips_used: {},
      purchase_prices_known: false,
      source_snapshot_id: "example-post-deadline-gw02",
      squadopt_comparison: null,
      data_quality: "empty",
      missing_fields: ["picks"],
    });
  }
  const players = squadPlayers(index);
  const partial = entry.data_quality === "partial";
  return envelope({
    league_id: LEAGUE_ID,
    season: SEASON,
    gameweek: GAMEWEEK,
    scored_gameweek: GAMEWEEK - 1,
    entry,
    starting_xi: partial ? players.starting.slice(0, 8) : players.starting,
    bench: partial ? players.bench.slice(0, 2) : players.bench,
    bank_tenths: 7,
    free_transfers: 1,
    free_transfers_known: false,
    chips_used: {},
    purchase_prices_known: false,
    source_snapshot_id: "example-post-deadline-gw02",
    squadopt_comparison: squadoptComparison,
    data_quality: partial ? "partial" : "complete",
    missing_fields: partial ? ["team_name", "gameweek_points", "picks[8:11]"] : [],
  });
}

export const mockEntrySquadEnvelopes = Object.fromEntries(
  mockMembers
    .filter((member): member is HumanEntryView => member.member_kind === "human")
    .map((member, index) => [member.entry_id, squadEnvelope(member, index)]),
) as Record<number, LeagueViewEnvelope<EntrySquad>>;

const advicePlayers = {
  out: { player_id: 109, name: "Kai Reed", short_name: "Reed", position: "FWD", team: "Northport" },
  safe: {
    player_id: 220,
    name: "Milo Green",
    short_name: "Green",
    position: "FWD",
    team: "Cityside",
  },
  aggressive: {
    player_id: 221,
    name: "Ayan Swift",
    short_name: "Swift",
    position: "FWD",
    team: "East Dock",
  },
  extreme: {
    player_id: 222,
    name: "Leo Bright",
    short_name: "Bright",
    position: "FWD",
    team: "Hill Athletic",
  },
} satisfies Record<string, import("../features/league/types").AdvicePlayer>;

function moveFor(mode: PlayMode, window: WindowSize): AdviceMove[] {
  if (mode === "saf-puan" && window === 1) return [];
  const incoming =
    mode === "garantici"
      ? advicePlayers.safe
      : mode === "asiri-agresif"
        ? advicePlayers.extreme
        : advicePlayers.aggressive;
  const cost = mode === "garantici" ? 1.6 : mode === "asiri-agresif" ? 1.5 : 1.8;
  return [
    {
      move_id: `${mode}-${window}-reed`,
      player_out: advicePlayers.out,
      player_in: incoming,
      expected_points_delta: Number((0.7 + window * 0.4).toFixed(1)),
      expected_points_cost: cost,
      reason_code: mode === "saf-puan" ? "window_value" : "mode_tradeoff",
    },
  ];
}

export function mockEntryAdviceEnvelope(
  entryId: number,
  mode: PlayMode,
  window: WindowSize,
): LeagueViewEnvelope<EntryAdvice> {
  const squad = mockEntrySquadEnvelopes[entryId]?.payload;
  const quality = squad?.data_quality ?? "empty";
  return envelope({
    league_id: LEAGUE_ID,
    season: SEASON,
    gameweek: GAMEWEEK,
    entry_id: entryId,
    mode,
    window,
    source_snapshot_id: "example-post-deadline-gw02",
    moves: quality === "complete" ? moveFor(mode, window) : [],
    // The producer prices the whole plan against the pure-points pick, in expected
    // points only; the example mirrors that shape so the page renders it in dev/test.
    expected_points_cost: mode === "saf-puan" ? 0 : 0.8,
    rival_label: mode === "saf-puan" ? null : "Harbor Rovers",
    data_quality: quality,
    missing_fields: quality === "complete" ? [] : (squad?.missing_fields ?? ["entry"]),
  });
}
