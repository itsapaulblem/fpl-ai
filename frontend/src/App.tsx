import { useEffect, useState } from "react";
import {
  Activity,
  Trophy,
  Wand2,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Crown,
  Sparkles,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import { api } from "./api";
import type {
  GameweekInfo,
  LiveScoresResponse,
  MyTeamResponse,
  PredictionsResponse,
  TransfersResponse,
} from "./types";

import { Card, CardBody, CardHeader } from "./components/Card";
import { Pitch } from "./components/Pitch";
import { PredictionsTable } from "./components/PredictionsTable";
import { TransferPlanCard } from "./components/TransferPlanCard";

const DEFAULT_TEAM_ID = 271610;
const MAX_TRANSFERS = 2;

export default function App() {
  // Team id input — type freely, applies on submit.
  const [teamIdInput, setTeamIdInput] = useState(String(DEFAULT_TEAM_ID));
  const [teamId, setTeamId] = useState<number>(DEFAULT_TEAM_ID);

  const [gw, setGw] = useState<GameweekInfo | null>(null);
  const [scores, setScores] = useState<LiveScoresResponse | null>(null);
  const [scoresGw, setScoresGw] = useState<number | null>(null);
  const [loadingScores, setLoadingScores] = useState(false);
  const [preds, setPreds] = useState<PredictionsResponse | null>(null);
  const [team, setTeam] = useState<MyTeamResponse | null>(null);
  const [transfers, setTransfers] = useState<TransfersResponse | null>(null);

  const [topN, setTopN] = useState(20);
  const [playerQuery, setPlayerQuery] = useState("");
  const [loadingTeam, setLoadingTeam] = useState(false);
  const [loadingTransfers, setLoadingTransfers] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial load — gameweek + live scores + top picks (don't depend on team id)
  useEffect(() => {
    (async () => {
      try {
        const [g, s, p] = await Promise.all([
          api.gameweek(),
          api.liveScores(),
          api.predictions(topN),
        ]);
        setGw(g);
        setScores(s);
        setScoresGw(s.gameweek);
        setPreds(p);
      } catch (e) {
        setError(String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload squad whenever the active team id changes
  useEffect(() => {
    (async () => {
      setLoadingTeam(true);
      setTeam(null);
      setTransfers(null);
      try {
        setTeam(await api.myTeam(teamId));
      } catch (e) {
        setError(String(e));
      } finally {
        setLoadingTeam(false);
      }
    })();
  }, [teamId]);

  // Reload fixtures whenever the user navigates to a different gameweek.
  useEffect(() => {
    if (scoresGw == null) return;
    let cancelled = false;
    (async () => {
      setLoadingScores(true);
      try {
        const s = await api.liveScores(scoresGw);
        if (!cancelled) setScores(s);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoadingScores(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scoresGw]);

  // Debounced live search of the predictions table.
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const q = playerQuery.trim();
        const limit = q ? 830 : topN;
        setPreds(await api.predictions(limit, undefined, q || undefined));
      } catch (e) {
        setError(String(e));
      }
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerQuery]);

  function applyTeamId() {
    const n = Number(teamIdInput);
    if (!Number.isInteger(n) || n <= 0) {
      setError("Please enter a valid FPL team id (positive integer).");
      return;
    }
    setError(null);
    setTeamId(n);
  }

  async function refreshPredictions() {
    setError(null);
    try {
      // When searching by name, widen the result set so we can scan everyone.
      const limit = playerQuery.trim() ? 830 : topN;
      setPreds(await api.predictions(limit, undefined, playerQuery.trim() || undefined));
    } catch (e) {
      setError(String(e));
    }
  }

  async function fetchTransfers() {
    if (!team) return;
    setError(null);
    setLoadingTransfers(true);
    try {
      setTransfers(
        await api.transfers(
          teamId,
          team.bank,
          team.free_transfers_estimate,
          MAX_TRANSFERS,
          5,
        ),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingTransfers(false);
    }
  }

  return (
    <div className="mx-auto min-h-screen max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <Header
        teamIdInput={teamIdInput}
        setTeamIdInput={setTeamIdInput}
        applyTeamId={applyTeamId}
        activeId={teamId}
      />

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-xl bg-danger/10 p-3 ring-1 ring-danger/30">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <pre className="overflow-auto whitespace-pre-wrap text-xs text-danger">
            {error}
          </pre>
        </div>
      )}

      {/* Live scores */}
      <section>
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-accent" />
                {(() => {
                  const shown = scores?.gameweek ?? scoresGw ?? gw?.next ?? null;
                  const next = gw?.next ?? null;
                  const cur = gw?.current ?? null;
                  let label = "Fixtures";
                  if (shown != null) {
                    if (shown === next) label = "Next Gameweek Fixtures";
                    else if (cur != null && shown < cur) label = "Past Fixtures";
                    else if (shown === cur) label = "Current Gameweek Fixtures";
                    else label = "Upcoming Fixtures";
                  }
                  return `${label} · GW${shown ?? "—"}`;
                })()}
              </span>
            }
            subtitle={
              gw?.current
                ? `Current gameweek: GW${gw.current}`
                : "Upcoming fixtures"
            }
            right={
              <div className="flex items-center gap-1">
                <button
                  onClick={() =>
                    setScoresGw((g) => Math.max(1, (g ?? gw?.next ?? 1) - 1))
                  }
                  disabled={
                    loadingScores || (scores?.gameweek ?? scoresGw ?? 1) <= 1
                  }
                  aria-label="Previous gameweek"
                  className="grid h-8 w-8 place-items-center rounded-lg bg-panel2 ring-1 ring-border hover:bg-panel2/70 disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[3.5rem] text-center text-xs font-semibold text-text">
                  GW{scores?.gameweek ?? scoresGw ?? "—"}
                </span>
                <button
                  onClick={() =>
                    setScoresGw((g) => Math.min(38, (g ?? gw?.next ?? 1) + 1))
                  }
                  disabled={
                    loadingScores || (scores?.gameweek ?? scoresGw ?? 38) >= 38
                  }
                  aria-label="Next gameweek"
                  className="grid h-8 w-8 place-items-center rounded-lg bg-panel2 ring-1 ring-border hover:bg-panel2/70 disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
                {gw?.next != null && (scores?.gameweek ?? scoresGw) !== gw.next && (
                  <button
                    onClick={() => setScoresGw(gw.next!)}
                    disabled={loadingScores}
                    className="ml-1 h-8 rounded-lg bg-accent px-2.5 text-[11px] font-semibold text-bg hover:bg-accent/80"
                  >
                    Jump to Upcoming GW
                  </button>
                )}
              </div>
            }
          />
          <CardBody>
            {scores ? <ScoresGrid scores={scores} /> : <Skeleton lines={4} />}
          </CardBody>
        </Card>
      </section>

      {/* Ideal Wildcard / Free Hit squads */}
      {/* (moved below the squad section) */}

      {/* Top predictions */}
      {/* (moved below the squad section) */}

      {/* Squad + Transfers grid */}
      <section className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <Trophy className="h-4 w-4 text-accent2" />
                  My current squad · GW{team?.snapshot_gameweek ?? "—"}
                </span>
              }
              subtitle={
                team
                  ? `Value £${team.squad_value.toFixed(1)}m · Bank £${team.bank.toFixed(1)}m · GW${team.snapshot_gameweek} points: ${team.event_points} · xP for GW${team.target_gameweek}: ${team.total_xpoints.toFixed(2)}`
                  : "Live FPL squad for this manager"
              }
            />
            <CardBody>
              {loadingTeam || !team ? (
                <Skeleton lines={10} />
              ) : (
                <>
                  <Pitch
                    startingXi={team.starting_xi}
                    bench={team.bench}
                    captainId={team.captain_id}
                    viceCaptainId={team.vice_captain_id}
                    formation={team.formation}
                  />
                  <CaptainRecommendation team={team} />
                  <ChipRecommendations team={team} />
                </>
              )}
            </CardBody>
          </Card>
        </div>

        <div>
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <Wand2 className="h-4 w-4 text-accent" /> Transfer plan
                </span>
              }
            />
            <CardBody className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <ReadOnlyField
                  label="Bank £m"
                  value={team ? team.bank.toFixed(1) : "—"}
                />
                <ReadOnlyField
                  label="Free transfers"
                  value={team ? String(team.free_transfers_estimate) : "—"}
                  hint={
                    team
                      ? `Made ${team.last_event_transfers} last GW`
                      : undefined
                  }
                />
              </div>
              <button
                onClick={fetchTransfers}
                disabled={loadingTransfers || !team}
                className="flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 text-sm font-semibold text-bg hover:bg-accent/80 disabled:opacity-60"
              >
                {loadingTransfers && (
                  <Loader2 className="h-4 w-4 animate-spin" />
                )}
                {loadingTransfers ? "Searching..." : "Recommend transfers"}
              </button>

              {transfers && (
                <div className="space-y-3 pt-2">
                  <div className="rounded-xl bg-panel2 p-3 ring-1 ring-border">
                    <p className="text-[11px] uppercase tracking-wider text-muted">
                      Best plan · GW{transfers.gameweek}
                    </p>
                    <p className="mt-1 text-2xl font-semibold text-accent2 tabular-nums">
                      +
                      {(
                        transfers.best.net_xpoints -
                        transfers.baseline.net_xpoints
                      ).toFixed(2)}{" "}
                      xP
                    </p>
                    <p className="text-xs text-muted">
                      vs holding current squad
                    </p>
                  </div>

                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">
                      Possible transfers
                    </p>
                    <div className="space-y-2">
                      {transfers.alternatives.slice(0, 5).map((p, i) => (
                        <TransferPlanCard
                          key={i}
                          plan={p}
                          baseline={transfers.baseline}
                          index={i}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {!transfers && !loadingTransfers && (
                <div className="flex items-start gap-2 rounded-lg bg-panel2/50 p-3 text-xs text-muted ring-1 ring-border">
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                  <span>
                    Bank and free transfers are pulled live. Click recommend to
                    see the best swap options.
                  </span>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </section>

      {/* Top predictions */}
      <section className="mt-6">
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-accent" />
                Top picks · GW{preds?.gameweek ?? "—"}
              </span>
            }
            subtitle="Players ranked by predicted xPoints for the next gameweek"
            right={
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="text"
                  placeholder="Search player or team…"
                  value={playerQuery}
                  onChange={(e) => setPlayerQuery(e.target.value)}
                  className="h-8 w-48 rounded-lg bg-panel2 px-2.5 text-sm ring-1 ring-border placeholder:text-muted focus:ring-accent"
                />
                <input
                  type="number"
                  min={1}
                  max={830}
                  value={topN}
                  onChange={(e) =>
                    setTopN(Math.max(1, Number(e.target.value) || 1))
                  }
                  disabled={!!playerQuery.trim()}
                  className="h-8 w-20 rounded-lg bg-panel2 px-2 text-sm ring-1 ring-border focus:ring-accent disabled:opacity-50"
                />
                <button
                  onClick={refreshPredictions}
                  className="h-8 rounded-lg bg-accent px-3 text-xs font-semibold text-bg hover:bg-accent/80"
                >
                  Refresh
                </button>
              </div>
            }
          />
          <CardBody>
            {preds ? (
              <PredictionsTable
                rows={preds.players}
                lastGw={preds.last_gameweek}
              />
            ) : (
              <Skeleton lines={6} />
            )}
          </CardBody>
        </Card>
      </section>

      {/* Ideal Wildcard / Free Hit squads */}
      {team && (team.ideal_squads?.wildcard || team.ideal_squads?.freehit) && (
        <section className="mt-6">
          <IdealSquadsBanner team={team} />
        </section>
      )}

      <footer className="mt-12 pb-6 text-center text-xs text-muted">
        Made by Paul Cheng · Data courtesy of the official Fantasy Premier League API
      </footer>
    </div>
  );
}

function Header({
  teamIdInput,
  setTeamIdInput,
  applyTeamId,
  activeId,
}: {
  teamIdInput: string;
  setTeamIdInput: (s: string) => void;
  applyTeamId: () => void;
  activeId: number;
}) {
  return (
    <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-chelsea ring-1 ring-accent/40">
          <span className="text-lg">⚽</span>
        </div>
        <div>
          <h1 className="text-lg font-semibold tracking-tight">
            FPL <span className="text-accent">AI</span>
          </h1>
          <p className="text-xs text-muted">
            Manager #{activeId} · Weekly Recommendations
          </p>
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          applyTeamId();
        }}
        className="flex items-center gap-2"
      >
        <div className="flex h-10 items-center gap-3 rounded-xl bg-panel2 px-4 ring-1 ring-border focus-within:ring-2 focus-within:ring-accent">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">
            FPL ID
          </span>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={teamIdInput}
            onChange={(e) =>
              setTeamIdInput(e.target.value.replace(/[^0-9]/g, ""))
            }
            placeholder="e.g. 271610"
            className="h-full w-32 bg-transparent text-sm font-medium tabular-nums outline-none placeholder:text-muted/50"
          />
        </div>
        <button
          type="submit"
          className="h-10 rounded-xl bg-accent px-4 text-sm font-semibold text-bg shadow-md shadow-accent/20 transition hover:bg-accent/80"
        >
          Load Team
        </button>
      </form>
    </header>
  );
}

function CaptainRecommendation({ team }: { team: MyTeamResponse }) {
  const [show, setShow] = useState(false);
  const ranked = [...team.starting_xi].sort((a, b) => b.xPoints - a.xPoints);
  const top = ranked[0];
  const second = ranked[1];
  const currentCaptainName =
    team.starting_xi.find((p) => p.player_id === team.captain_id)?.web_name ?? "—";

  if (!top) return null;
  const isAlreadyCaptain = top.player_id === team.captain_id;

  return (
    <div className="mt-4 rounded-xl bg-panel2 p-3 ring-1 ring-border">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-muted">
          <Crown className="h-3.5 w-3.5 text-accent2" />
          Captain Pick
        </div>
        <button
          onClick={() => setShow((s) => !s)}
          className="h-7 rounded-md bg-accent px-2.5 text-[11px] font-semibold text-bg hover:bg-accent/80"
        >
          {show ? "Hide" : "Recommend Captain"}
        </button>
      </div>
      {show && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-lg bg-bg/40 p-2 ring-1 ring-border">
            <p className="text-[10px] uppercase tracking-wider text-muted">
              Captain (C)
            </p>
            <p className="font-semibold">{top.web_name}</p>
            <p className="text-xs text-accent">
              {top.xPoints.toFixed(2)} xP · {top.team_name}
            </p>
          </div>
          {second && (
            <div className="rounded-lg bg-bg/40 p-2 ring-1 ring-border">
              <p className="text-[10px] uppercase tracking-wider text-muted">
                Vice (V)
              </p>
              <p className="font-semibold">{second.web_name}</p>
              <p className="text-xs text-accent">
                {second.xPoints.toFixed(2)} xP · {second.team_name}
              </p>
            </div>
          )}
          <p className="col-span-2 text-[11px] text-muted">
            {isAlreadyCaptain
              ? `You're already captaining ${top.web_name} — nice pick.`
              : `You're currently captaining ${currentCaptainName}. Switching the armband to ${top.web_name} maximises expected points.`}
          </p>
        </div>
      )}
    </div>
  );
}

function ChipRecommendations({ team }: { team: MyTeamResponse }) {
  const [show, setShow] = useState(false);
  const recs = team.chip_recommendations ?? [];
  const remaining = team.chips_remaining;
  const totalRemaining = remaining
    ? remaining.wildcard + remaining.freehit + remaining.bboost + remaining["3xc"]
    : 0;

  return (
    <div className="mt-3 rounded-xl bg-panel2 p-3 ring-1 ring-border">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-muted">
          <Sparkles className="h-3.5 w-3.5 text-accent2" />
          Chip Strategy
          <span className="rounded-md bg-bg/40 px-1.5 py-0.5 text-[10px] text-text">
            {totalRemaining} left
          </span>
        </div>
        {recs.length > 0 && (
          <button
            onClick={() => setShow((s) => !s)}
            className="h-7 rounded-md bg-accent px-2.5 text-[11px] font-semibold text-bg hover:bg-accent/80"
          >
            {show ? "Hide" : "Recommend Chip"}
          </button>
        )}
      </div>
      {totalRemaining === 0 && (
        <p className="mt-2 text-[11px] text-muted">
          All chips used this season! Nothing left to activate...
        </p>
      )}
      {show && recs.length > 0 && (
        <div className="mt-3 space-y-2">
          {recs.map((r) => (
            <div
              key={r.chip}
              className={`rounded-lg p-2 ring-1 ${
                r.recommend
                  ? "bg-accent2/10 ring-accent2/40"
                  : "bg-bg/40 ring-border"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold">{r.label}</p>
                <p className="text-xs text-accent">
                  {r.xpoints_with_chip.toFixed(1)} xP
                  <span className="ml-1 text-muted">
                    (+{r.delta.toFixed(1)})
                  </span>
                </p>
              </div>
              {r.chip !== "bboost" && (
                <p className="mt-0.5 text-[11px] text-muted">{r.note}</p>
              )}

              {r.chip === "3xc" && r.captain_name && (
                <div className="mt-2 flex items-center justify-between rounded-md bg-bg/60 px-2 py-1.5 ring-1 ring-border">
                  <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted">
                    <Crown className="h-3 w-3 text-accent2" />
                    Captain
                  </div>
                  <div className="flex items-center gap-1.5">
                    {r.captain_team_code ? (
                      <img
                        src={`https://resources.premierleague.com/premierleague/badges/50/t${r.captain_team_code}.png`}
                        alt=""
                        className="h-4 w-4 object-contain"
                        loading="lazy"
                      />
                    ) : null}
                    <p className="text-xs font-semibold text-text">
                      {r.captain_name}
                      <span className="ml-1.5 text-accent">
                        {(r.captain_xpoints ?? 0).toFixed(1)} xP
                      </span>
                    </p>
                  </div>
                </div>
              )}

              {r.chip === "bboost" && r.bench_players && r.bench_players.length > 0 && (
                <div className="mt-2 space-y-1 rounded-md bg-bg/60 px-2 py-1.5 ring-1 ring-border">
                  <p className="text-[10px] uppercase tracking-wider text-muted">
                    Your bench
                  </p>
                  {r.bench_players.map((b) => (
                    <div
                      key={b.player_id}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span className="flex min-w-0 items-center gap-1.5 truncate">
                        <span className="rounded bg-panel2 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted">
                          {b.position}
                        </span>
                        {b.team_code ? (
                          <img
                            src={`https://resources.premierleague.com/premierleague/badges/50/t${b.team_code}.png`}
                            alt=""
                            className="h-4 w-4 shrink-0 object-contain"
                            loading="lazy"
                          />
                        ) : null}
                        <span className="truncate">{b.name}</span>
                      </span>
                      <span className="tabular-nums font-semibold text-accent">
                        {b.xpoints.toFixed(1)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          <p className="text-[10px] text-muted">
            xP shown is the projected total for GW{team.target_gameweek} if you
            play the chip this week.
          </p>
        </div>
      )}
    </div>
  );
}

function IdealSquadsBanner({ team }: { team: MyTeamResponse }) {
  const wc = team.ideal_squads?.wildcard ?? null;
  const fh = team.ideal_squads?.freehit ?? null;
  const cards: Array<{
    key: "wildcard" | "freehit";
    title: string;
    badge: string;
    subtitle: string;
    sq: NonNullable<typeof wc>;
  }> = [];
  if (wc)
    cards.push({
      key: "wildcard",
      title: "Ideal Wildcard Squad",
      badge: `Avg over GW${wc.gameweek}–${wc.horizon_end ?? wc.gameweek}`,
      subtitle: `Long-term build · optimised for the next ${wc.horizon} gameweeks`,
      sq: wc,
    });
  if (fh)
    cards.push({
      key: "freehit",
      title: "Ideal Free Hit Squad",
      badge: `GW${fh.gameweek} only`,
      subtitle: "One-week punt · maximum points for the next gameweek",
      sq: fh,
    });

  if (cards.length === 0) return null;

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-accent2" />
            Chip Squad Builder
          </span>
        }
        subtitle="What your team would look like if you played a Wildcard or Free Hit this week"
      />
      <CardBody>
        <div
          className={`grid gap-4 ${cards.length === 2 ? "lg:grid-cols-2" : ""}`}
        >
          {cards.map((c) => (
            <IdealSquadCard
              key={c.key}
              title={c.title}
              badge={c.badge}
              subtitle={c.subtitle}
              squad={c.sq}
              currentXp={team.total_xpoints}
            />
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function IdealSquadCard({
  title,
  badge,
  subtitle,
  squad,
  currentXp,
}: {
  title: string;
  badge: string;
  subtitle: string;
  squad: NonNullable<MyTeamResponse["ideal_squads"]["wildcard"]>;
  currentXp: number;
}) {
  const delta = squad.total_xpoints - currentXp;
  const positive = delta > 0;
  return (
    <div className="rounded-xl bg-panel2 p-3 ring-1 ring-border">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-text">{title}</p>
          <p className="text-[11px] text-muted">{subtitle}</p>
        </div>
        <span className="rounded-md bg-bg/40 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted ring-1 ring-border">
          {badge}
        </span>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <span className="text-muted">
          Formation:{" "}
          <span className="font-semibold text-text">{squad.formation}</span>
        </span>
        <span className="text-muted">
          Cost:{" "}
          <span className="font-semibold text-text">
            £{squad.total_cost.toFixed(1)}m
          </span>
        </span>
        <span className="text-muted">
          xP:{" "}
          <span className="font-semibold text-accent">
            {squad.total_xpoints.toFixed(1)}
          </span>
        </span>
        <span
          className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
            positive
              ? "bg-accent2/15 text-accent2"
              : "bg-bg/40 text-muted"
          }`}
        >
          {positive ? "+" : ""}
          {delta.toFixed(1)} vs current
        </span>
      </div>
      <Pitch
        startingXi={squad.starting_xi}
        bench={squad.bench}
        captainId={squad.captain_id}
        viceCaptainId={squad.vice_captain_id}
        formation={squad.formation}
      />
    </div>
  );
}

function ScoresGrid({ scores }: { scores: LiveScoresResponse }) {
  if (scores.fixtures.length === 0) {
    return (
      <p className="text-sm text-muted">
        No fixtures scheduled for this gameweek.
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {scores.fixtures.map((f) => {
        const live = f.started && !f.finished;
        const showScore = f.home_score != null && f.away_score != null;
        const statusBadge = f.finished
          ? "FT"
          : live
            ? `${f.minutes}'`
            : f.kickoff_time
              ? new Date(f.kickoff_time).toLocaleString(undefined, {
                  weekday: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "TBD";
        return (
          <div
            key={f.id}
            className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-lg bg-panel2 px-3 py-2 ring-1 ring-border"
          >
            <div className="flex items-center justify-end gap-2 min-w-0">
              {f.home_code != null && (
                <img
                  src={`https://resources.premierleague.com/premierleague/badges/50/t${f.home_code}.png`}
                  alt=""
                  className="h-6 w-6 shrink-0 object-contain"
                  loading="lazy"
                />
              )}
              <span className="truncate text-sm font-medium">{f.home_short}</span>
            </div>
            <div className="flex flex-col items-center">
              <span className="text-base font-semibold tabular-nums leading-none text-text">
                {showScore ? `${f.home_score} - ${f.away_score}` : "vs"}
              </span>
              <span
                className={`mt-1 text-[10px] font-semibold uppercase tracking-wider ${
                  live ? "text-accent2" : f.finished ? "text-muted" : "text-muted"
                }`}
              >
                ({statusBadge})
              </span>
            </div>
            <div className="flex items-center justify-start gap-2 min-w-0">
              <span className="truncate text-sm font-medium">{f.away_short}</span>
              {f.away_code != null && (
                <img
                  src={`https://resources.premierleague.com/premierleague/badges/50/t${f.away_code}.png`}
                  alt=""
                  className="h-6 w-6 shrink-0 object-contain"
                  loading="lazy"
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ReadOnlyField({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg bg-panel2 px-3 py-2 ring-1 ring-border">
      <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-[10px] text-muted">{hint}</p>}
    </div>
  );
}

function Skeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="h-4 w-full animate-pulse rounded bg-panel2" />
      ))}
    </div>
  );
}
