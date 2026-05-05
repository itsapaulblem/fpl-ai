import { useState, useMemo } from "react";
import { ArrowUp, ArrowDown } from "lucide-react";
import type { PlayerPrediction } from "../types";
import { PositionBadge } from "./PositionBadge";
import { money } from "../lib/utils";

type SortKey = "player" | "team" | "pos" | "price" | "lastGw" | "xPts";
type SortDir = "asc" | "desc";

const POSITION_ORDER: Record<string, number> = { GKP: 0, DEF: 1, MID: 2, FWD: 3 };

export function PredictionsTable({
  rows,
  lastGw,
}: {
  rows: PlayerPrediction[];
  lastGw?: number | null;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("xPts");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "player":
          cmp = a.web_name.localeCompare(b.web_name);
          break;
        case "team":
          cmp = a.team_name.localeCompare(b.team_name);
          break;
        case "pos":
          cmp = (POSITION_ORDER[a.position] ?? 99) - (POSITION_ORDER[b.position] ?? 99);
          break;
        case "price":
          cmp = a.price - b.price;
          break;
        case "lastGw":
          cmp = (a.last_gw_points ?? -1) - (b.last_gw_points ?? -1);
          break;
        case "xPts":
        default:
          cmp = a.xPoints - b.xPoints;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [rows, sortKey, sortDir]);

  function toggle(key: SortKey, defaultDir: SortDir = "desc") {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(defaultDir);
    }
  }

  if (!rows.length)
    return <p className="text-sm text-muted">No predictions available.</p>;

  const max = Math.max(...sorted.map((r) => r.xPoints));
  const showLast = !!lastGw;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-left font-medium">#</th>
            <SortHeader label="Player" active={sortKey === "player"} dir={sortDir} onClick={() => toggle("player", "asc")} align="left" />
            <SortHeader label="Team" active={sortKey === "team"} dir={sortDir} onClick={() => toggle("team", "asc")} align="left" />
            <SortHeader label="Pos" active={sortKey === "pos"} dir={sortDir} onClick={() => toggle("pos", "asc")} align="left" />
            <SortHeader label="Price" active={sortKey === "price"} dir={sortDir} onClick={() => toggle("price")} align="right" />
            {showLast && (
              <SortHeader
                label={`GW${lastGw} Pts`}
                active={sortKey === "lastGw"}
                dir={sortDir}
                onClick={() => toggle("lastGw")}
                align="right"
              />
            )}
            <SortHeader label="xPts" active={sortKey === "xPts"} dir={sortDir} onClick={() => toggle("xPts")} align="right" />
            <th className="hidden px-3 py-2 sm:table-cell" />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr
              key={r.player_id}
              className="border-b border-border/60 hover:bg-panel2/60"
            >
              <td className="px-3 py-2 text-muted">{i + 1}</td>
              <td className="px-3 py-2 font-medium text-text">
                <div className="flex items-center gap-2">
                  {r.photo_code ? (
                    <img
                      src={`https://resources.premierleague.com/premierleague/photos/players/110x140/p${r.photo_code}.png`}
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                      }}
                      alt=""
                      loading="lazy"
                      className="h-8 w-7 shrink-0 rounded object-cover bg-panel2"
                    />
                  ) : (
                    <div className="h-8 w-7 shrink-0 rounded bg-panel2" />
                  )}
                  <span>{r.web_name}</span>
                </div>
              </td>
              <td className="px-3 py-2 text-muted">{r.team_name}</td>
              <td className="px-3 py-2">
                <PositionBadge pos={r.position} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-text">
                {money(r.price)}
              </td>
              {showLast && (
                <td className="px-3 py-2 text-right tabular-nums text-text">
                  {r.last_gw_minutes ? (
                    <span
                      className={
                        (r.last_gw_points ?? 0) >= 6
                          ? "font-semibold text-accent2"
                          : (r.last_gw_points ?? 0) >= 3
                            ? "text-text"
                            : "text-muted"
                      }
                    >
                      {r.last_gw_points ?? 0}
                    </span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
              )}
              <td className="px-3 py-2 text-right tabular-nums font-semibold text-accent">
                {r.xPoints.toFixed(2)}
              </td>
              <td className="hidden w-32 px-3 py-2 sm:table-cell">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${(r.xPoints / max) * 100}%` }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SortHeader({
  label,
  active,
  dir,
  onClick,
  align,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
  align: "left" | "right";
}) {
  return (
    <th className={`px-3 py-2 font-medium ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex items-center gap-1 hover:text-text ${
          active ? "text-accent" : ""
        }`}
      >
        <span>{label}</span>
        {active &&
          (dir === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          ))}
      </button>
    </th>
  );
}
