import { ArrowRight } from "lucide-react";
import type { TransferPlan } from "../types";

export function TransferPlanCard({
  plan,
  baseline,
  index,
}: {
  plan: TransferPlan;
  baseline: TransferPlan;
  index: number;
}) {
  const delta = plan.net_xpoints - baseline.net_xpoints;
  const positive = delta >= 0;

  return (
    <div className="rounded-xl bg-panel2 p-4 ring-1 ring-border">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wider text-muted">
          Option {index + 1} · {plan.n_transfers} transfer{plan.n_transfers === 1 ? "" : "s"}
          {plan.hit_cost > 0 && (
            <span className="ml-2 rounded bg-warn/20 px-2 py-0.5 text-xs font-bold text-warn ring-1 ring-warn/40">
              −{plan.hit_cost} pts hit
            </span>
          )}
        </span>
        <span
          className={`text-sm font-semibold tabular-nums ${
            positive ? "text-accent" : "text-danger"
          }`}
        >
          {positive ? "+" : ""}
          {delta.toFixed(2)} xP
        </span>
      </div>

      {plan.transfers_out.length === 0 ? (
        <p className="text-sm text-muted">No transfers — keep current squad.</p>
      ) : (
        <div className="space-y-2">
          {plan.transfers_out.map((out, i) => {
            const inP = plan.transfers_in[i];
            return (
              <div
                key={`${out.player_id}-${inP?.player_id}`}
                className="flex items-center gap-2 text-sm"
              >
                <span className="flex-1 truncate text-danger">{out.name}</span>
                <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted" />
                <span className="flex-1 truncate text-accent">{inP?.name}</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px] text-muted">
        <span>XI xP: <span className="font-semibold text-text">{plan.xi_xpoints.toFixed(2)}</span></span>
        <span>Net xP: <span className="font-semibold text-text">{plan.net_xpoints.toFixed(2)}</span></span>
        <span>Bank: <span className="font-semibold text-text">£{plan.bank_after.toFixed(1)}m</span></span>
      </div>
    </div>
  );
}
