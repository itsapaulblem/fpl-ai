export type Health = {
  status: string;
  model_trained_through_gw: number;
  model_val_rmse: number;
  n_players: number;
};

export type GameweekInfo = {
  current: number | null;
  next: number | null;
  next_deadline: string | null;
};

export type LiveFixture = {
  id: number;
  kickoff_time: string | null;
  started: boolean;
  finished: boolean;
  minutes: number;
  home_team: string;
  home_short: string;
  home_code: number | null;
  away_team: string;
  away_short: string;
  away_code: number | null;
  home_score: number | null;
  away_score: number | null;
};

export type LiveScoresResponse = {
  gameweek: number;
  fixtures: LiveFixture[];
};

export type Position = "GKP" | "DEF" | "MID" | "FWD";

export type PlayerPrediction = {
  player_id: number;
  web_name: string;
  team_name: string;
  position: Position;
  team: number;
  team_code?: number;
  photo_code?: number;
  price: number;
  n_fixtures: number;
  is_home: number;
  opp_strength: number;
  xPoints: number;
  last_gw_points?: number;
  last_gw_minutes?: number;
};

export type PredictionsResponse = {
  gameweek: number;
  last_gameweek?: number | null;
  count: number;
  players: PlayerPrediction[];
};

export type SquadPlayer = {
  player_id: number;
  web_name: string;
  team_name: string;
  team_code?: number;
  photo_code?: number;
  position: Position;
  price: number;
  xPoints: number;
  last_gw_points?: number;
  last_gw_minutes?: number;
};

export type SquadResponse = {
  gameweek: number;
  budget: number;
  total_cost: number;
  total_xpoints: number;
  formation: string;
  captain_id: number;
  vice_captain_id: number;
  starting_xi: SquadPlayer[];
  bench: SquadPlayer[];
};

export type TransferMove = { player_id: number; name: string };

export type TransferPlan = {
  transfers_out: TransferMove[];
  transfers_in: TransferMove[];
  n_transfers: number;
  hit_cost: number;
  xi_xpoints: number;
  net_xpoints: number;
  bank_after: number;
  formation: string;
  captain_id: number;
  captain_name?: string;
};

export type MyTeamPlayer = SquadPlayer & {
  squad_slot: number;
  multiplier: number;
  is_captain: boolean;
  is_vice_captain: boolean;
};

export type ChipBenchPlayer = {
  player_id: number;
  name: string;
  position: string;
  team_name: string;
  team_code?: number;
  xpoints: number;
};

export type ChipRecommendation = {
  chip: "bboost" | "3xc";
  label: string;
  xpoints_with_chip: number;
  delta: number;
  recommend: boolean;
  note: string;
  breakdown?: string;
  captain_name?: string;
  captain_id?: number;
  captain_xpoints?: number;
  captain_team_code?: number;
  bench_players?: ChipBenchPlayer[];
};

export type ChipUsage = { name: string; event: number; time: string };

export type IdealSquad = {
  formation: string;
  captain_id: number;
  vice_captain_id: number;
  total_xpoints: number;
  total_cost: number;
  delta_vs_current: number;
  horizon: number;
  gameweek: number;
  horizon_end?: number;
  starting_xi: MyTeamPlayer[];
  bench: MyTeamPlayer[];
};

export type MyTeamResponse = {
  team_id: number;
  snapshot_gameweek: number;
  target_gameweek: number;
  bank: number;
  squad_value: number;
  total_budget: number;
  free_transfers_estimate: number;
  last_event_transfers: number;
  event_points: number;
  total_points: number;
  formation: string;
  captain_id: number;
  vice_captain_id: number;
  total_xpoints: number;
  starting_xi: MyTeamPlayer[];
  bench: MyTeamPlayer[];
  chips_remaining: { wildcard: number; freehit: number; bboost: number; "3xc": number };
  chips_used: ChipUsage[];
  chip_recommendations: ChipRecommendation[];
  ideal_squads: {
    wildcard: IdealSquad | null;
    freehit: IdealSquad | null;
  };
};

export type TransfersResponse = {
  gameweek: number;
  team_id: number;
  bank: number;
  free_transfers: number;
  baseline: TransferPlan;
  best: TransferPlan;
  alternatives: TransferPlan[];
};

export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ChatResponse = {
  reply: string;
};

// ----- Leagues -----
export type ManagerLeague = {
  id: number;
  name: string;
  short_name: string | null;
  entry_rank: number | null;
  entry_last_rank: number | null;
  league_type: string;
  is_invitational: boolean;
};

export type ManagerLeaguesResponse = {
  manager_id: number;
  manager_name: string;
  team_name: string;
  leagues: ManagerLeague[];
};

export type LeagueStandingRow = {
  entry_id: number;
  entry_name: string;
  player_name: string;
  rank: number;
  last_rank?: number | null;
  rank_sort?: number | null;
  total: number;
  event_total: number;
  predicted_xpoints: number | null;
  is_me: boolean;
};

export type LeagueResponse = {
  league_id: number;
  league_name: string;
  league_admin_entry?: number | null;
  snapshot_gameweek: number;
  target_gameweek: number;
  average_predicted_xpoints: number | null;
  standings: LeagueStandingRow[];
  you: LeagueStandingRow | null;
  has_next: boolean;
};

export type RivalSquadPlayer = {
  player_id: number;
  web_name: string;
  team_name: string;
  team_code: number;
  position: string;
  price: number;
  xPoints: number;
  squad_slot?: number;
  is_captain?: boolean;
  is_vice_captain?: boolean;
};

export type RivalSwapSuggestion = RivalSquadPlayer & { xp_gain: number };

export type RivalWeakness = {
  weak_player: RivalSquadPlayer;
  reason: string;
  suggested_replacements: RivalSwapSuggestion[];
};

export type RivalManagerResponse = {
  league_id: number;
  manager_id: number;
  entry_name: string;
  player_name: string;
  snapshot_gameweek: number;
  target_gameweek: number;
  captain_id: number;
  vice_captain_id: number;
  xi_xpoints: number;
  total_xpoints: number;
  starting_xi: RivalSquadPlayer[];
  bench: RivalSquadPlayer[];
  weaknesses: RivalWeakness[];
};
