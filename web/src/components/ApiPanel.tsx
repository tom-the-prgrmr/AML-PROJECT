import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, apiGet } from "../api/client";
import type { Envelope } from "../api/types";
import { errorCodeLabel } from "../i18n";
import { IconAlert } from "./icons";
import SourceBadge from "./SourceBadge";

type State<T> =
  | { kind: "loading" }
  | { kind: "ok"; envelope: Envelope<T> }
  | { kind: "error"; code: string; message: string };

interface Props<T> {
  path: string;
  title?: string;
  children: (data: T, meta: Record<string, unknown>, reload: () => void) => ReactNode;
}

/** The only way a page gets API data: fetch, label the source, or show an empty state. */
export default function ApiPanel<T>({ path, title, children }: Props<T>) {
  const [state, setState] = useState<State<T>>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  // A new path starts from "loading". A reload keeps the old data on screen until the new
  // response arrives; an error then replaces it, so no stale number stays next to an error.
  useEffect(() => {
    setState({ kind: "loading" });
  }, [path]);

  useEffect(() => {
    let cancelled = false;
    apiGet<T>(path)
      .then((envelope) => {
        if (!cancelled) setState({ kind: "ok", envelope });
      })
      .catch((e: unknown) => {
        const code = e instanceof ApiError ? e.code : "unknown_error";
        const message = e instanceof ApiError ? e.message : "Lỗi không xác định";
        if (!cancelled) setState({ kind: "error", code, message });
      });
    return () => {
      cancelled = true;
    };
  }, [path, version]);

  return (
    <section className="panel" aria-busy={state.kind === "loading"}>
      {state.kind === "ok" && state.envelope.source === "mock" && <SourceBadge />}
      {title && <h2>{title}</h2>}
      {state.kind === "loading" && <Loading />}
      {state.kind === "error" && <Failure code={state.code} message={state.message} />}
      {state.kind === "ok" && children(state.envelope.data, state.envelope.meta, reload)}
    </section>
  );
}

function Loading() {
  return (
    <div className="skeleton-stack" role="status">
      <span className="sr-only">Đang tải...</span>
      <span className="skeleton" />
      <span className="skeleton" />
      <span className="skeleton" />
      <span className="skeleton" />
    </div>
  );
}

/** No data: the stable error code, what it means in Vietnamese, and the server's own message. */
function Failure({ code, message }: { code: string; message: string }) {
  const meaning = errorCodeLabel(code);
  return (
    <div className="alert alert-danger" role="alert">
      <IconAlert />
      <div>
        <strong className="alert-title">Chưa có dữ liệu</strong>
        <code>{code}</code>
        {meaning !== code && ` ${meaning}.`} {message}
      </div>
    </div>
  );
}
