import { cn } from "../lib/utils";
import type { Position } from "../types";

const COLORS: Record<Position, string> = {
  GKP: "bg-gkp/15 text-gkp ring-gkp/30",
  DEF: "bg-def/15 text-def ring-def/30",
  MID: "bg-mid/15 text-mid ring-mid/30",
  FWD: "bg-fwd/15 text-fwd ring-fwd/30",
};

export function PositionBadge({ pos, className }: { pos: Position; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1",
        COLORS[pos],
        className,
      )}
    >
      {pos}
    </span>
  );
}
