import { useEffect, useMemo, useState } from "react";
import {
  Trophy,
  Loader2,
  AlertTriangle,
  Swords,
  Crown,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  ChevronDown,
} from "lucide-react";

import { api } from "../api";
import type {
  LeagueResponse,
  LeagueStandingRow,
  ManagerLeague,
  RivalManagerResponse,
  RivalWeakness,
} from "../types";
import { Card, CardBody, CardHeader } from "./Card";
import type { ChatContext } from "./RoseniorChat";

type Props = {
  myTeamId: number;
  /** Called when the user clicks "Ask Liam" — parent opens chat with context
   * and (optionally) an auto-send prompt to fire off without typing. */
  onAskLiam: (ctx: ChatContext, autoPrompt?: string) => void;
};

const LAST_LEAGUE_KEY = "fpl-ai.last-league-id";

export function LeagueTab({ myTeamId, onAskLiam }: Props) {
  // ----- Manager's leagues (auto-discovered from FPL id) ---------------
  const [leagues, setLeagues] = useState<ManagerLeague[] | null>(null);
  const [leaguesError, setLeaguesError] = useState<string | null>(null);
  const [loadingLeagues, setLoadingLeagues] = useState(false);
  const [leagueId, setLeagueId] = useState<number | null>(null);

  // ----- Selected league standings -------------------------------------
  const [data, setData] = useState<LeagueResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ----- Scout sub-page (rival drilldown) ------------------------------
  const [scoutId, setScoutId] = useState<number | null>(null);
  const [rival, setRival] = useState<RivalManagerResponse | null>(null);
  const [rivalLoading, setRivalLoading] = useState(false);
  const [rivalError, setRivalError] = useState<string | null>(null);

  // Auto-fetch the manager's leagues whenever the FPL id changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingLeagues(true);
      setLeaguesError(null);
      setLeagues(null);
      setData(null);
      setLeagueId(null);
      setScoutId(null);
      setRival(null);
      try {
        const r = await api.managerLeagues(myTeamId);
        if (cancelled) return;
        setLeagues(r.leagues);
        // Pick a sensible default: last-used league if it's in the list,
        // otherwise the first invitational league.
        const last = Number(localStorage.getItem(LAST_LEAGUE_KEY) || 0);
        const pick =
          r.leagues.find((l) => l.id === last) ??
          r.leagues.find((l) => l.is_invitational) ??
          r.leagues[0] ??
          null;
        if (pick) setLeagueId(pick.id);
      } catch (e) {
        if (!cancelled) setLeaguesError(String(e));
      } finally {
        if (!cancelled) setLoadingLeagues(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [myTeamId]);

  // Fetch league standings whenever the selected league changes.
  useEffect(() => {
    if (leagueId == null) return;
    localStorage.setItem(LAST_LEAGUE_KEY, String(leagueId));
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setData(null);
      setScoutId(null);
      setRival(null);
      try {
        const d = await api.league(leagueId, myTeamId, undefined, 25);
        if (!cancelled) setData(d);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leagueId, myTeamId]);

  // Fetch rival drilldown when one is selected (scout sub-page).
  useEffect(() => {
    if (leagueId == null || scoutId == null) return;
    let cancelled = false;
    (async () => {
      setRivalLoading(true);
      setRivalError(null);
      setRival(null);
      try {
        const r = await api.leagueManager(leagueId, scoutId);
        if (!cancelled) setRival(r);
      } catch (e) {
        if (!cancelled) setRivalError(String(e));
      } finally {
        if (!cancelled) setRivalLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leagueId, scoutId]);

  // The user's predicted XI xP (always enriched server-side for `is_me`).
  const myXp = data?.standings.find((r) => r.is_me)?.predicted_xpoints ?? null;

  // Build the league-wide chat context (used for "Ask Liam about this league").
  const leagueChatContext: ChatContext | null = useMemo(() => {
    if (!data) return null;
    const top = data.standings.slice(0, 15);
    const lines = top.map((r) => {
      const xp =
        r.predicted_xpoints != null ? `${r.predicted_xpoints.toFixed(1)} xP` : "?";
      const me = r.is_me ? " ← ME" : "";
      return `#${r.rank} ${r.player_name} (${r.entry_name}) — ${r.total} pts, GW xP ${xp}${me}`;
    });
    const mePart = data.you
      ? `\nThe user is manager #${data.you.entry_id} (${data.you.player_name}, "${data.you.entry_name}"), currently rank ${data.you.rank} with ${data.you.total} total pts. Their predicted XI xP for GW${data.target_gameweek} is ${myXp ?? "n/a"}.`
      : `\nThe user's manager id is ${myTeamId}.`;
    return {
      label: `League: ${data.league_name}`,
      text:
        `FPL classic mini-league "${data.league_name}" (id ${data.league_id}). ` +
        `Snapshot GW${data.snapshot_gameweek}, predicting GW${data.target_gameweek}. ` +
        `Average predicted XI xP across enriched managers: ${data.average_predicted_xpoints ?? "n/a"}.${mePart}\n\n` +
        `Top standings:\n${lines.join("\n")}`,
    };
  }, [data, myTeamId, myXp]);

  // Build rival-specific chat context (used in scout sub-page).
  const rivalChatContext: ChatContext | null = useMemo(() => {
    if (!data || !rival) return null;
    const weakLines = rival.weaknesses
      .map((w, i) => {
        const wp = w.weak_player;
        const subs = w.suggested_replacements
          .slice(0, 3)
          .map(
            (s) =>
              `    → ${s.web_name} (${s.team_name}, £${s.price.toFixed(1)}m, ${s.xPoints.toFixed(1)} xP, +${s.xp_gain.toFixed(1)})`,
          )
          .join("\n");
        return `  ${i + 1}. ${wp.web_name} (${wp.position}, ${wp.team_name}, £${wp.price.toFixed(1)}m, ${wp.xPoints.toFixed(1)} xP)\n${subs || "    (no clear upgrades within budget)"}`;
      })
      .join("\n");
    const xiLines = rival.starting_xi
      .map(
        (p) =>
          `  - ${p.web_name} (${p.position}, ${p.team_name}, ${p.xPoints.toFixed(1)} xP)${p.is_captain ? " [C]" : p.is_vice_captain ? " [V]" : ""}`,
      )
      .join("\n");

    const meRow = data.standings.find((r) => r.is_me);
    const rivalRow = data.standings.find((r) => r.entry_id === rival.manager_id);
    const gap =
      meRow && rivalRow
        ? `Total-points gap: ${meRow.total - rivalRow.total} (me − rival).`
        : "";

    return {
      label: `vs ${rival.player_name || rival.entry_name || "rival"}`,
      text:
        `FPL mini-league "${data.league_name}". The user wants to overtake rival manager #${rival.manager_id} ` +
        `(${rival.player_name}, team "${rival.entry_name}"). ${gap}\n` +
        `User's predicted XI xP for GW${rival.target_gameweek}: ${myXp ?? "n/a"}. ` +
        `Rival's predicted XI xP: ${rival.xi_xpoints} (with captain bonus: ${rival.total_xpoints}).\n\n` +
        `Rival's starting XI for GW${rival.target_gameweek}:\n${xiLines}\n\n` +
        `Their weakest starters and concrete upgrade swaps the user could consider for differentials:\n${weakLines}`,
    };
  }, [data, rival, myXp]);

  // ----- Scout sub-page ------------------------------------------------
  if (scoutId != null) {
    return (
      <ScoutPage
        rival={rival}
        loading={rivalLoading}
        error={rivalError}
        onBack={() => {
          setScoutId(null);
          setRival(null);
          setRivalError(null);
        }}
        onAskLiam={() => {
          if (rival && rivalChatContext) {
            const prompt =
              `Coach, give me a sharp tactical plan to overtake ${rival.player_name || rival.entry_name} ` +
              `in our mini-league this gameweek. Use the live context: which of their weak XI starters should I target with my own transfers, ` +
              `which differentials from the suggested swaps look most exploitable given form and fixtures, ` +
              `and what captain or chip should I play to widen the gap? Be concrete and concise.`;
            onAskLiam(rivalChatContext, prompt);
          }
        }}
        myXp={myXp}
      />
    );
  }

  // ----- Main league view ----------------------------------------------
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-accent2" />
              Mini-League Standings
            </span>
          }
          subtitle="Auto-loaded from your FPL id — pick a league to scout your rivals."
        />
        <CardBody>
          {loadingLeagues && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              Finding your leagues…
            </div>
          )}

          {leaguesError && (
            <div className="flex items-start gap-2 rounded-xl bg-danger/10 p-3 ring-1 ring-danger/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-xs text-danger">{leaguesError}</p>
            </div>
          )}

          {!loadingLeagues && leagues && leagues.length === 0 && (
            <p className="text-sm text-muted">
              No mini-leagues found for FPL id #{myTeamId}.
            </p>
          )}

          {leagues && leagues.length > 0 && (
            <LeaguePicker
              leagues={leagues}
              value={leagueId}
              onChange={setLeagueId}
            />
          )}

          {error && (
            <div className="mt-3 flex items-start gap-2 rounded-xl bg-danger/10 p-3 ring-1 ring-danger/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-xs text-danger">{error}</p>
            </div>
          )}

          {loading && (
            <div className="mt-4 flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading league…
            </div>
          )}

          {data && !loading && (
            <div className="mt-4 space-y-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="text-base font-semibold text-text">
                    {data.league_name}
                  </p>
                  <p className="text-[11px] text-muted">
                    Snapshot GW{data.snapshot_gameweek} · predicting GW
                    {data.target_gameweek} · {data.standings.length} managers
                    {data.has_next ? "+" : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {data.average_predicted_xpoints != null && (
                    <span className="rounded-md bg-panel2 px-2 py-0.5 text-xs text-muted ring-1 ring-border">
                      Avg XI xP:{" "}
                      <span className="font-semibold text-text">
                        {data.average_predicted_xpoints.toFixed(1)}
                      </span>
                    </span>
                  )}
                  {leagueChatContext && (
                    <button
                      type="button"
                      onClick={() => {
                        const prompt =
                          `Coach, take a look at our mini-league "${data.league_name}". ` +
                          `Where do I sit relative to my rivals for GW${data.target_gameweek}, ` +
                          `who's the biggest threat in the next few weeks, and which two or three concrete moves ` +
                          `(captain, transfers, chips) would give me the best shot at climbing the standings? Keep it sharp.`;
                        onAskLiam(leagueChatContext, prompt);
                      }}
                      className="flex h-8 items-center gap-1.5 rounded-lg bg-accent2/20 px-3 text-xs font-semibold text-accent2 ring-1 ring-accent2/40 hover:bg-accent2/30"
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      Ask Liam about this league
                    </button>
                  )}
                </div>
              </div>

              {data.you && !data.standings.some((r) => r.is_me) && (
                <div className="rounded-xl bg-accent/10 p-3 text-sm ring-1 ring-accent/30">
                  You are <span className="font-semibold">#{data.you.rank}</span>{" "}
                  ({data.you.player_name}, {data.you.total} pts) — outside the
                  enriched top {data.standings.length}.
                </div>
              )}

              <StandingsTable
                rows={data.standings}
                avgXp={data.average_predicted_xpoints ?? null}
                myXp={myXp}
                onScout={(id) => setScoutId(id)}
              />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function LeaguePicker({
  leagues,
  value,
  onChange,
}: {
  leagues: ManagerLeague[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">
        Your Leagues
      </span>
      <div className="relative">
        <select
          value={value ?? ""}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-10 appearance-none rounded-xl bg-panel2 pl-3 pr-9 text-sm font-medium text-text ring-1 ring-border focus:outline-none focus:ring-2 focus:ring-accent"
        >
          {leagues.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
              {l.entry_rank ? ` · #${l.entry_rank}` : ""}
              {l.is_invitational ? "" : " (system)"}
            </option>
          ))}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
      </div>
    </div>
  );
}

function StandingsTable({
  rows,
  avgXp,
  myXp,
  onScout,
}: {
  rows: LeagueStandingRow[];
  avgXp: number | null;
  myXp: number | null;
  onScout: (id: number) => void;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted">No standings to show.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-xl ring-1 ring-border">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-panel2 text-[11px] uppercase tracking-wider text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Rank</th>
            <th className="px-3 py-2 text-left">Manager</th>
            <th className="px-3 py-2 text-left">Team</th>
            <th className="px-3 py-2 text-right">Total</th>
            <th className="px-3 py-2 text-right">My xP</th>
            <th className="px-3 py-2 text-right">Their xP</th>
            <th className="px-3 py-2 text-right">vs Avg</th>
            <th className="px-3 py-2 text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const theirXp = r.is_me ? null : r.predicted_xpoints;
            const diff =
              avgXp != null && r.predicted_xpoints != null
                ? r.predicted_xpoints - avgXp
                : null;
            return (
              <tr
                key={r.entry_id}
                className={`border-t border-border transition ${
                  r.is_me ? "bg-accent/10" : "hover:bg-panel2/50"
                }`}
              >
                <td className="px-3 py-2 font-semibold tabular-nums">
                  #{r.rank}
                </td>
                <td className="px-3 py-2">
                  <span className="font-medium text-text">{r.player_name}</span>
                  {r.is_me && (
                    <span className="ml-2 rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent">
                      You
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-muted">{r.entry_name}</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums">
                  {r.total}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {myXp != null ? (
                    <span className="font-semibold text-accent">
                      {myXp.toFixed(1)}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {theirXp != null ? (
                    <span
                      className={
                        myXp != null && theirXp > myXp
                          ? "font-semibold text-danger"
                          : "font-semibold text-text"
                      }
                    >
                      {theirXp.toFixed(1)}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {diff != null ? (
                    <span className={diff >= 0 ? "text-accent2" : "text-danger"}>
                      {diff >= 0 ? "+" : ""}
                      {diff.toFixed(1)}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {r.is_me ? (
                    <span className="text-[11px] text-muted">—</span>
                  ) : (
                    <button
                      onClick={() => onScout(r.entry_id)}
                      className="inline-flex h-7 items-center gap-1 rounded-md bg-panel2 px-2 text-[11px] font-semibold text-text ring-1 ring-border hover:bg-accent2 hover:text-bg"
                    >
                      Scout
                      <ArrowRight className="h-3 w-3" />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// =====================================================================
// Scout sub-page (rival drilldown)
// =====================================================================
function ScoutPage({
  rival,
  loading,
  error,
  onBack,
  onAskLiam,
  myXp,
}: {
  rival: RivalManagerResponse | null;
  loading: boolean;
  error: string | null;
  onBack: () => void;
  onAskLiam: () => void;
  myXp: number | null;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          onClick={onBack}
          className="flex h-9 items-center gap-1.5 rounded-lg bg-panel2 px-3 text-sm font-semibold text-text ring-1 ring-border hover:bg-panel2/70"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to standings
        </button>
        {rival && (
          <button
            onClick={onAskLiam}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-accent2 px-3 text-sm font-semibold text-bg shadow-md shadow-accent2/20 hover:bg-accent2/80"
          >
            <Sparkles className="h-4 w-4" />
            Ask Liam how to exploit
          </button>
        )}
      </div>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Swords className="h-4 w-4 text-accent2" />
              Rival Scout · {rival?.player_name || (loading ? "Loading…" : "—")}
            </span>
          }
          subtitle={rival?.entry_name ? `Team: ${rival.entry_name}` : undefined}
        />
        <CardBody>
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Scouting rival…
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 rounded-xl bg-danger/10 p-3 ring-1 ring-danger/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <p className="text-xs text-danger">{error}</p>
            </div>
          )}
          {rival && !loading && <RivalDetail rival={rival} myXp={myXp} />}
        </CardBody>
      </Card>
    </div>
  );
}

function RivalDetail({
  rival,
  myXp,
}: {
  rival: RivalManagerResponse;
  myXp: number | null;
}) {
  const xpDelta = myXp != null ? rival.xi_xpoints - myXp : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="My GW xP" value={myXp != null ? myXp.toFixed(1) : "—"} accent />
        <Stat label="Their GW xP" value={rival.xi_xpoints.toFixed(1)} />
        <Stat
          label="Diff"
          value={
            xpDelta != null
              ? `${xpDelta >= 0 ? "+" : ""}${xpDelta.toFixed(1)}`
              : "—"
          }
          tone={xpDelta == null ? "neutral" : xpDelta < 0 ? "good" : "bad"}
        />
        <Stat
          label="Their captain"
          value={
            rival.starting_xi.find((p) => p.player_id === rival.captain_id)
              ?.web_name || "—"
          }
        />
      </div>

      <div>
        <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
          Their starting XI (sorted by xP)
        </p>
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {[...rival.starting_xi]
            .sort((a, b) => b.xPoints - a.xPoints)
            .map((p) => (
              <div
                key={p.player_id}
                className="flex items-center gap-2 rounded-md bg-panel2 px-2 py-1.5 text-xs ring-1 ring-border"
              >
                {p.team_code ? (
                  <img
                    src={`https://resources.premierleague.com/premierleague/badges/50/t${p.team_code}.png`}
                    alt=""
                    className="h-4 w-4 shrink-0 object-contain"
                    loading="lazy"
                  />
                ) : null}
                <span className="rounded bg-bg/40 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted">
                  {p.position}
                </span>
                <span className="flex-1 truncate font-medium">{p.web_name}</span>
                {p.is_captain && (
                  <Crown className="h-3 w-3 shrink-0 text-accent2" />
                )}
                <span className="tabular-nums font-semibold text-accent">
                  {p.xPoints.toFixed(1)}
                </span>
              </div>
            ))}
        </div>
      </div>

      <div>
        <p className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted">
          <AlertTriangle className="h-3 w-3 text-warn" />
          Weak Spots & Upgrade Swaps
        </p>
        {rival.weaknesses.length === 0 ? (
          <p className="text-sm text-muted">
            No clear weak spots — this team's solid.
          </p>
        ) : (
          <div className="space-y-3">
            {rival.weaknesses.map((w, i) => (
              <WeaknessCard key={i} weakness={w} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function WeaknessCard({
  weakness,
  index,
}: {
  weakness: RivalWeakness;
  index: number;
}) {
  const wp = weakness.weak_player;
  return (
    <div className="rounded-xl bg-warn/5 p-3 ring-1 ring-warn/30">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded bg-warn/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
            #{index + 1} weakest
          </span>
          {wp.team_code ? (
            <img
              src={`https://resources.premierleague.com/premierleague/badges/50/t${wp.team_code}.png`}
              alt=""
              className="h-5 w-5 object-contain"
              loading="lazy"
            />
          ) : null}
          <span className="font-semibold text-text">{wp.web_name}</span>
          <span className="text-[11px] text-muted">
            {wp.position} · {wp.team_name} · £{wp.price.toFixed(1)}m
          </span>
        </div>
        <span className="rounded bg-bg/40 px-1.5 py-0.5 text-xs font-semibold tabular-nums text-warn">
          {wp.xPoints.toFixed(1)} xP
        </span>
      </div>
      <p className="mt-1 text-[11px] text-muted">{weakness.reason}</p>

      {weakness.suggested_replacements.length > 0 ? (
        <div className="mt-2 space-y-1">
          <p className="text-[10px] uppercase tracking-wider text-muted">
            Differentials you could field instead
          </p>
          {weakness.suggested_replacements.map((s) => (
            <div
              key={s.player_id}
              className="flex items-center gap-2 rounded-md bg-panel2 px-2 py-1.5 text-xs ring-1 ring-border"
            >
              {s.team_code ? (
                <img
                  src={`https://resources.premierleague.com/premierleague/badges/50/t${s.team_code}.png`}
                  alt=""
                  className="h-4 w-4 shrink-0 object-contain"
                  loading="lazy"
                />
              ) : null}
              <span className="flex-1 truncate font-medium">{s.web_name}</span>
              <span className="text-[10px] text-muted">
                {s.team_name} · £{s.price.toFixed(1)}m
              </span>
              <span className="tabular-nums font-semibold text-accent">
                {s.xPoints.toFixed(1)} xP
              </span>
              <span className="rounded bg-accent2/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent2 tabular-nums">
                +{s.xp_gain.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-muted">
          No same-position upgrades found within £0.5m of their price.
        </p>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  tone = "neutral",
}: {
  label: string;
  value: string;
  accent?: boolean;
  tone?: "neutral" | "good" | "bad";
}) {
  const ring =
    tone === "good"
      ? "bg-accent2/10 ring-accent2/40"
      : tone === "bad"
        ? "bg-danger/10 ring-danger/40"
        : accent
          ? "bg-accent/10 ring-accent/40"
          : "bg-panel2 ring-border";
  const valueClr =
    tone === "good"
      ? "text-accent2"
      : tone === "bad"
        ? "text-danger"
        : accent
          ? "text-accent"
          : "text-text";
  const labelClr =
    tone === "good"
      ? "text-accent2"
      : tone === "bad"
        ? "text-danger"
        : accent
          ? "text-accent"
          : "text-muted";
  return (
    <div className={`rounded-lg p-2.5 ring-1 ${ring}`}>
      <p className={`text-[10px] uppercase tracking-wider ${labelClr}`}>
        {label}
      </p>
      <p className={`mt-0.5 text-lg font-bold ${valueClr}`}>{value}</p>
    </div>
  );
}
