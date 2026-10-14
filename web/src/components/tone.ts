/** The five status tones of the design system and the badge class of each. */
export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export const BADGE_CLASS: Record<Tone, string> = {
  success: "badge badge-ok",
  warning: "badge badge-warn",
  danger: "badge badge-bad",
  info: "badge badge-info",
  neutral: "badge badge-neutral",
};
