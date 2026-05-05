import type { PlayerPrediction } from "../types";
import { PositionBadge } from "./PositionBadge";
import { money } from "../lib/utils";

export function PredictionsTable({
  rows,
  lastGw,
}: {
  rows: PlayerPrediction[];
  lastGw?: number | null;
}) {
  if (!rows.length)
    return <p className="text-sm text-muted">No predictions available.</p>;

  const max = Math.max(...rows.map((r) => r.xPoints));
  const showLast = !!lastGw;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-[11px] uppercase tracking-wider text-muted">
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-left font-medium">#</th>
            <th className="px-3 py-2 text-left font-medium">Player</th>
            <th className="px-3 py-2 text-left font-medium">Team</th>
            <th className="px-3 py-2 text-left font-medium">Pos</th>
            <th className="px-3 py-2 text-right font-medium">Price</th>
            {showLast && (
              <th className="px-3 py-2 text-right font-medium">
                GW{lastGw} Pts
              </th>
            )}
            <th className="px-3 py-2 text-right font-medium">xPts</th>
            <th className="hidden px-3 py-2 sm:table-cell" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r.player_id}
              className="border-b border-border/60 hover:bg-panel2/60"
            >
              <td className="px-3 py-2 text-muted">{i + 1}</td>
              <td className="px-3 py-2 font-medium text-text">{r.web_name}</td>
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
