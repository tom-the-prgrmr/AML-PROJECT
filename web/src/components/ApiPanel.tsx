import { useEffect, useState, type ReactNode } from "react";
import { ApiError, apiGet } from "../api/client";
import type { Envelope } from "../api/types";
import SourceBadge from "./SourceBadge";

type State<T> =
  | { kind: "loading" }
  | { kind: "ok"; envelope: Envelope<T> }
  | { kind: "error"; code: string };

interface Props<T> {
  path: string;
  title?: string;
  children: (data: T) => ReactNode;
}

/** The only way a page gets API data: fetch, label the source, or show an empty state. */
export default function ApiPanel<T>({ path, title, children }: Props<T>) {
  const [state, setState] = useState<State<T>>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    apiGet<T>(path)
      .then((envelope) => {
        if (!cancelled) setState({ kind: "ok", envelope });
      })
      .catch((e: unknown) => {
        const code = e instanceof ApiError ? e.code : "unknown_error";
        if (!cancelled) setState({ kind: "error", code });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return (
    <section className="panel">
      {state.kind === "ok" && state.envelope.source === "mock" && <SourceBadge />}
      {title && <h2>{title}</h2>}
      {state.kind === "loading" && <p className="muted">Đang tải...</p>}
      {state.kind === "error" && (
        <p className="empty">
          Chưa có dữ liệu <code>{state.code}</code>
        </p>
      )}
      {state.kind === "ok" && children(state.envelope.data)}
    </section>
  );
}
