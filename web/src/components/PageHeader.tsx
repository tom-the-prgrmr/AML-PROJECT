import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

/** Title of a page (its only h1), an optional line under it, and optional actions on the right. */
export default function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
