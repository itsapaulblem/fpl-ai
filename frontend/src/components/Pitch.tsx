import { cn } from "../lib/utils";
import type { Position, SquadPlayer } from "../types";
import { PositionBadge } from "./PositionBadge";

const ROW_BY_POS: Record<Position, number> = {
  GKP: 0,
  DEF: 1,
  MID: 2,
  FWD: 3,
};

function PlayerChip({
  player,
  isCaptain,
  isVice,
}: {
  player: SquadPlayer;
  isCaptain?: boolean;
  isVice?: boolean;
}) {
  return (
    <div className="flex w-24 flex-col items-center gap-1 sm:w-28">
      <div className="relative">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-panel2 ring-2 ring-border sm:h-14 sm:w-14">
          {player.team_code ? (
            <img
              src={`https://resources.premierleague.com/premierleague/badges/50/t${player.team_code}.png`}
              alt=""
              className="h-8 w-8 object-contain sm:h-9 sm:w-9"
              loading="lazy"
            />
          ) : (
            <PositionBadge pos={player.position} className="text-[9px]" />
          )}
        </div>
        {isCaptain && (
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-bg ring-2 ring-bg">
            C
          </span>
        )}
        {isVice && (
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-accent2 text-[10px] font-bold text-white ring-2 ring-bg">
            V
          </span>
        )}
      </div>
      <p className="flex max-w-full items-center gap-1 truncate text-center text-[11px] font-medium text-text">
        <PositionBadge pos={player.position} className="text-[8px]" />
        <span className="truncate">{player.web_name}</span>
      </p>
      <div className="flex items-center gap-1 text-[10px] text-muted">
        <span>£{player.price.toFixed(1)}</span>
        <span>·</span>
        <span className="text-accent">{player.xPoints.toFixed(1)} xP</span>
      </div>
    </div>
  );
}

export function Pitch({
  startingXi,
  bench,
  captainId,
  viceCaptainId,
  formation,
}: {
  startingXi: SquadPlayer[];
  bench: SquadPlayer[];
  captainId: number;
  viceCaptainId: number;
  formation: string;
}) {
  const rows: Record<Position, SquadPlayer[]> = { GKP: [], DEF: [], MID: [], FWD: [] };
  for (const p of startingXi) rows[p.position].push(p);
  // Stable sort within row by xPoints desc
  (Object.keys(rows) as Position[]).forEach((k) =>
    rows[k].sort((a, b) => b.xPoints - a.xPoints),
  );

  const orderedRows: Position[] = ["GKP", "DEF", "MID", "FWD"];

  return (
    <div className="space-y-4">
      <div
        className={cn(
          "relative overflow-hidden rounded-2xl ring-1 ring-border",
          "bg-gradient-to-b from-emerald-900/40 via-emerald-900/25 to-emerald-950/40",
        )}
        style={{
          backgroundImage:
            "repeating-linear-gradient(0deg, rgba(255,255,255,0.04) 0 24px, transparent 24px 48px)",
        }}
      >
        {/* pitch markings */}
        <div className="pointer-events-none absolute inset-3 rounded-xl border border-white/15" />
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/15" />
        <div className="pointer-events-none absolute left-3 right-3 top-1/2 h-px bg-white/15" />

        <div className="relative z-10 flex flex-col justify-around px-4 py-6 sm:px-8 sm:py-10">
          {orderedRows.map((pos) => (
            <div
              key={pos}
              className="flex justify-around"
              style={{ marginTop: ROW_BY_POS[pos] === 0 ? 0 : 16 }}
            >
              {rows[pos].map((p) => (
                <PlayerChip
                  key={p.player_id}
                  player={p}
                  isCaptain={p.player_id === captainId}
                  isVice={p.player_id === viceCaptainId}
                />
              ))}
            </div>
          ))}
        </div>

        <div className="absolute right-3 top-3 rounded-md bg-bg/70 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted ring-1 ring-border">
          {formation}
        </div>
      </div>

      <div>
        <p className="mb-2 text-[11px] uppercase tracking-wider text-muted">Bench</p>
        <div className="flex flex-wrap gap-3 rounded-xl bg-panel2 p-3 ring-1 ring-border">
          {bench.map((p) => (
            <PlayerChip key={p.player_id} player={p} />
          ))}
        </div>
      </div>
    </div>
  );
}
