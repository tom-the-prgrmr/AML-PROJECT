import {
  ALERT_SOURCE_LABELS,
  BENCH_STATUS_LABELS,
  CASE_STATUS_LABELS,
  DASH,
  DISPOSITION_LABELS,
  DQ_STATUS_LABELS,
  REVIEW_DECISION_LABELS,
  SCREENING_DECISION_LABELS,
  labelOf,
  type Labels,
} from "../i18n";
import { BADGE_CLASS, type Tone } from "./tone";

export type BadgeKind =
  | "caseStatus"
  | "disposition"
  | "screeningDecision"
  | "reviewDecision"
  | "dqStatus"
  | "benchStatus"
  | "source";

const KINDS: Record<BadgeKind, { labels: Labels; tones: Record<string, Tone> }> = {
  caseStatus: {
    labels: CASE_STATUS_LABELS,
    tones: { OPEN: "info", REOPENED: "warning", CLOSED: "neutral" },
  },
  disposition: {
    labels: DISPOSITION_LABELS,
    tones: { SUSPICIOUS: "danger", FALSE_POSITIVE: "success" },
  },
  screeningDecision: {
    labels: SCREENING_DECISION_LABELS,
    tones: { ALERT: "danger", REVIEW: "warning", AUTO_CLEARED: "success" },
  },
  reviewDecision: {
    labels: REVIEW_DECISION_LABELS,
    tones: { TRUE_MATCH: "danger", FALSE_MATCH: "success" },
  },
  dqStatus: {
    labels: DQ_STATUS_LABELS,
    tones: { PASS: "success", FAIL: "danger", NO_DATA: "neutral" },
  },
  benchStatus: {
    labels: BENCH_STATUS_LABELS,
    tones: { ok: "success", skipped: "neutral", error: "danger" },
  },
  // A source is a category, not a state, so it carries no status colour.
  source: { labels: ALERT_SOURCE_LABELS, tones: {} },
};

interface Props {
  kind: BadgeKind;
  value: string | null | undefined;
}

/**
 * A coded value as a badge with its Vietnamese label. The label carries the meaning and the
 * colour only supports it. An unknown value is shown as is, in the neutral tone.
 */
export default function StatusBadge({ kind, value }: Props) {
  if (value === null || value === undefined || value === "") {
    return <span className="muted">{DASH}</span>;
  }
  const { labels, tones } = KINDS[kind];
  const tone = Object.prototype.hasOwnProperty.call(tones, value) ? tones[value] : "neutral";
  return <span className={BADGE_CLASS[tone]}>{labelOf(labels, value)}</span>;
}
