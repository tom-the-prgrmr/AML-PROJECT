import type { ReactNode } from "react";

/** Inline icons: one 24px grid, one stroke style, decorative (the label next to it speaks). */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Product mark: a shield. */
export function IconBrand() {
  return (
    <Icon>
      <path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  );
}

/** Case queue: an inbox tray. */
export function IconCases() {
  return (
    <Icon>
      <path d="M4 13l2.5-8h11L20 13v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5z" />
      <path d="M4 13h4.5l1 2h5l1-2H20" />
    </Icon>
  );
}

/** Screening review: a person under a magnifier. */
export function IconScreening() {
  return (
    <Icon>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4-4" />
      <circle cx="11" cy="9.5" r="2" />
      <path d="M7.5 14.5c.8-1.5 2-2.2 3.5-2.2s2.7.7 3.5 2.2" />
    </Icon>
  );
}

/** Data quality: a database cylinder with a check. */
export function IconDataQuality() {
  return (
    <Icon>
      <ellipse cx="11" cy="6" rx="7" ry="3" />
      <path d="M4 6v6c0 1.7 3.1 3 7 3" />
      <path d="M4 12v6c0 1.7 3.1 3 7 3" />
      <path d="M18 6v5" />
      <path d="M14.5 18l2 2 4-4" />
    </Icon>
  );
}

/** Benchmark: a stopwatch. */
export function IconBenchmark() {
  return (
    <Icon>
      <circle cx="12" cy="14" r="7" />
      <path d="M12 14l3-3" />
      <path d="M10 3h4" />
      <path d="M12 3v4" />
    </Icon>
  );
}

/** Metrics: a bar chart. */
export function IconMetrics() {
  return (
    <Icon>
      <path d="M4 20h16" />
      <path d="M7 20v-7" />
      <path d="M12 20V5" />
      <path d="M17 20v-10" />
    </Icon>
  );
}

/** System: two server units. */
export function IconSystem() {
  return (
    <Icon>
      <rect x="4" y="4" width="16" height="7" rx="1.5" />
      <rect x="4" y="13" width="16" height="7" rx="1.5" />
      <path d="M8 7.5h.01" />
      <path d="M8 16.5h.01" />
    </Icon>
  );
}

/** Warning triangle, for inline alerts. */
export function IconAlert() {
  return (
    <Icon>
      <path d="M12 4l9 16H3l9-16z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </Icon>
  );
}
