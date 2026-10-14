import type { ReactNode } from "react";

interface Props {
  title: string;
  hint?: ReactNode;
}

/** What a list or panel shows when there is nothing to show, and what to do about it. */
export default function EmptyState({ title, hint }: Props) {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {hint && <p className="empty-state-hint">{hint}</p>}
    </div>
  );
}
