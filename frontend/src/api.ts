import type {
  ChatMessage,
  ChatResponse,
  GameweekInfo,
  Health,
  LiveScoresResponse,
  MyTeamResponse,
  PredictionsResponse,
  SquadResponse,
  TransfersResponse,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${path} ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/health"),
  gameweek: () => get<GameweekInfo>("/gameweek"),
  liveScores: (gw?: number) =>
    get<LiveScoresResponse>(`/live-scores${gw ? `?gw=${gw}` : ""}`),
  predictions: (top = 50, gw?: number, q?: string) =>
    get<PredictionsResponse>(
      `/predictions?top=${top}${gw ? `&gw=${gw}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),
  squad: (budget = 100, gw?: number) =>
    get<SquadResponse>(`/squad?budget=${budget}${gw ? `&gw=${gw}` : ""}`),
  myTeam: (tid: number, gw?: number) =>
    get<MyTeamResponse>(`/my-team?tid=${tid}${gw ? `&gw=${gw}` : ""}`),
  transfers: (
    tid: number,
    bank = 0,
    free = 1,
    maxTransfers = 2,
    top = 5,
    gw?: number,
  ) =>
    get<TransfersResponse>(
      `/transfers?tid=${tid}&bank=${bank}&free=${free}` +
        `&max_transfers=${maxTransfers}&top=${top}${gw ? `&gw=${gw}` : ""}`,
    ),
  chat: (messages: ChatMessage[]) =>
    post<ChatResponse>("/chat", { messages }),
};
