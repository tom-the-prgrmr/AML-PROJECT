/**
 * Display formatting. Pure string reshaping: nothing here rounds a number (except
 * `formatPercent`, whose `digits` says so) or shifts a timestamp to another time zone.
 */
export const DASH = "—";

type Missing = null | undefined;

/** "—" for a missing value (null, undefined, empty string), else the value as text. */
export function dash(value: unknown): string {
  return value === null || value === undefined || value === "" ? DASH : String(value);
}

/** vi-VN digits: "." groups thousands, "," is the decimal mark. Every digit is kept. */
export function formatNumber(n: number | Missing): string {
  if (n === null || n === undefined) return DASH;
  const text = String(n);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text; // NaN, Infinity, 1e+21: show as is
  const [whole, fraction] = text.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return fraction === undefined ? grouped : `${grouped},${fraction}`;
}

/** An amount in VND, e.g. 161398000 -> "161.398.000". The unit belongs in the column header. */
export function formatVnd(n: number | Missing): string {
  return formatNumber(n);
}

/** A ratio as a percentage rounded to `digits` decimals: (0.0125, 2) -> "1,25%". */
export function formatPercent(ratio: number | Missing, digits = 2): string {
  if (ratio === null || ratio === undefined) return DASH;
  return `${(ratio * 100).toFixed(digits).replace(".", ",")}%`;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})/;
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(.*)$/;

/** "YYYY-MM-DD..." -> "dd/MM/yyyy" (the date part only). Other text is returned unchanged. */
export function formatDate(value: string | Missing): string {
  if (value === null || value === undefined || value === "") return DASH;
  const m = DATE.exec(value);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : value;
}

/**
 * "YYYY-MM-DDTHH:MM:SS" -> "dd/MM/yyyy HH:mm:ss". A date without a time is formatted as a date.
 * Whatever follows the seconds (fraction, "Z", "+00:00") is kept as written, so a zone the
 * backend did send is never dropped.
 */
export function formatDateTime(value: string | Missing): string {
  if (value === null || value === undefined || value === "") return DASH;
  const m = DATE_TIME.exec(value);
  if (!m) return formatDate(value);
  const seconds = m[6] === undefined ? "" : `:${m[6]}`;
  return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}${seconds}${m[7]}`;
}

/** true -> "Có", false -> "Không". */
export function yesNo(value: boolean | Missing): string {
  if (value === null || value === undefined) return DASH;
  return value ? "Có" : "Không";
}
