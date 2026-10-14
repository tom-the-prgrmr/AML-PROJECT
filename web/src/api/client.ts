import type { Envelope } from "./types";

const PREFIX = "/api/v1";
export const USER_KEY = "aml.user";

export class ApiError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

export function getStoredUser(): string | null {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

export function storeUser(actor: string): void {
  try {
    localStorage.setItem(USER_KEY, actor);
  } catch {
    // Storage may be blocked; the server then falls back to its default actor.
  }
}

export function clearStoredUser(): void {
  try {
    localStorage.removeItem(USER_KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Turn a response body into an Envelope. A body of unknown origin is never shown. */
export function parseEnvelope<T>(body: unknown, ok = true): Envelope<T> {
  if (!ok) {
    const err = isRecord(body) && isRecord(body.error) ? body.error : {};
    const code = typeof err.code === "string" ? err.code : "unknown_error";
    const message = typeof err.message === "string" ? err.message : "Lỗi không xác định";
    throw new ApiError(code, message);
  }
  if (!isRecord(body) || (body.source !== "live" && body.source !== "mock")) {
    throw new ApiError("unknown_source", "Phản hồi không rõ nguồn dữ liệu");
  }
  return body as unknown as Envelope<T>;
}

async function request<T>(method: string, path: string, payload?: unknown): Promise<Envelope<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const user = getStoredUser();
  if (user) headers["X-AML-User"] = user;
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(PREFIX + path, {
      method,
      headers,
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
  } catch {
    throw new ApiError("network_error", "Không kết nối được máy chủ");
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return parseEnvelope<T>(body, response.ok);
}

export function apiGet<T>(path: string): Promise<Envelope<T>> {
  return request<T>("GET", path);
}

export function apiPost<T>(path: string, payload: unknown): Promise<Envelope<T>> {
  return request<T>("POST", path, payload);
}
