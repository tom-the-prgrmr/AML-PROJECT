import type { ReactNode } from "react";
import type { Tone } from "./tone";

interface Props {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}

/** One summary tile: a small label over a large value. Put several inside `.stat-row`. */
export default function Stat({ label, value, hint, tone }: Props) {
  return (
    <div className={tone ? `stat stat-${tone}` : "stat"}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}
