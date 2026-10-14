import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiGet } from "../api/client";
import type { CaseScore, CaseScores } from "../api/insightTypes";
import type { CaseRow } from "../api/types";
import EmptyState from "../components/EmptyState";
import { IconAlert } from "../components/icons";
import PageHeader from "../components/PageHeader";
import Pager from "../components/Pager";
import Stat from "../components/Stat";
import StatusBadge from "../components/StatusBadge";
import {
  CASE_STATUS_LABELS,
  DASH,
  dash,
  errorCodeLabel,
  featureLabel,
  formatDate,
  formatDateTime,
  formatNumber,
} from "../i18n";
import "./case/overview.css";

/** The filter values the endpoint accepts; null is "every status". */
const STATUSES: (string | null)[] = [null, ...Object.keys(CASE_STATUS_LABELS)];

/** Rows per screen (the table pages on the client). Requests use the API's own default page size. */
const PAGE_SIZE = 50;

interface Loaded {
  rows: CaseRow[];
  scores: Map<string, CaseScore>;
  runId: unknown;
  asOf: unknown;
}

type State =
  | { kind: "loading" }
  | { kind: "ok"; data: Loaded }
  | { kind: "error"; code: string; message: string };

/** Every page of `GET /cases` (the endpoint pages by time) and the priority scores, in one load. */
async function loadAll(): Promise<Loaded> {
  const rows: CaseRow[] = [];
  let first: Record<string, unknown> = {};
  let offset = 0;
  for (;;) {
    const page = await apiGet<CaseRow[]>(`/cases?offset=${offset}`);
    if (offset === 0) first = page.meta;
    rows.push(...page.data);
    const total = Number(page.meta.total ?? rows.length);
    const limit = Number(page.meta.limit ?? page.data.length);
    offset += limit;
    if (page.data.length === 0 || offset >= total || limit <= 0) break;
  }
  const scores = await apiGet<CaseScores>("/cases/scores");
  return {
    rows,
    scores: new Map(scores.data.scores.map((s) => [s.case_id, s])),
    runId: first.run_id,
    asOf: first.as_of,
  };
}

/** Ranked cases first by `queue_rank`; the rest keep the order the API gave them. */
function ranked(rows: CaseRow[], scores: Map<string, CaseScore>): CaseRow[] {
  const rankOf = (c: CaseRow): number | null => scores.get(c.case_id)?.queue_rank ?? null;
  const withRank = rows.filter((c) => rankOf(c) !== null);
  if (withRank.length === 0) return rows;
  withRank.sort((a, b) => (rankOf(a) ?? 0) - (rankOf(b) ?? 0));
  return [...withRank, ...rows.filter((c) => rankOf(c) === null)];
}

function CaseTable({ rows, scores }: { rows: CaseRow[]; scores: Map<string, CaseScore> }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Mã case</th>
            <th>Khách hàng gộp</th>
            <th className="num">Điểm ưu tiên</th>
            <th className="num">Hạng</th>
            <th>Yếu tố chính</th>
            <th>Trạng thái</th>
            <th>Quyết định</th>
            <th>Nguồn cảnh báo</th>
            <th className="num">Số cảnh báo</th>
            <th>Cảnh báo gần nhất</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const score = scores.get(c.case_id);
            const rank = score?.queue_rank ?? null;
            return (
              <tr key={c.case_id}>
                <td>
                  <Link className="code nowrap" to={`/cases/${c.case_id}`}>
                    {c.case_id}
                  </Link>
                </td>
                <td className="code">{c.golden_customer_id}</td>
                <td className="num">{score === undefined ? DASH : formatNumber(score.score)}</td>
                <td className="num">{rank === null ? DASH : formatNumber(rank)}</td>
                <td>{featureLabel(score?.top_features[0]?.feature)}</td>
                <td>
                  <StatusBadge kind="caseStatus" value={c.status} />
                </td>
                <td>
                  {c.disposition === null ? (
                    <span className="muted">Chưa có</span>
                  ) : (
                    <>
                      <StatusBadge kind="disposition" value={c.disposition.disposition} />
                      <span className="cell-sub">
                        <span className="code">{c.disposition.actor}</span>, ngày{" "}
                        {formatDate(c.disposition.decided_on)}
                      </span>
                    </>
                  )}
                </td>
                <td>
                  <span className="badge-list">
                    {c.sources.map((source) => (
                      <StatusBadge key={source} kind="source" value={source} />
                    ))}
                  </span>
                </td>
                <td className="num">{formatNumber(c.alerts)}</td>
                <td>{formatDateTime(c.last_alert_ts)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function CasesPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadAll()
      .then((data) => {
        if (!cancelled) setState({ kind: "ok", data });
      })
      .catch((e: unknown) => {
        const code = e instanceof ApiError ? e.code : "unknown_error";
        const message = e instanceof ApiError ? e.message : "Lỗi không xác định";
        if (!cancelled) setState({ kind: "error", code, message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const data = state.kind === "ok" ? state.data : null;
  const sorted = useMemo(() => (data ? ranked(data.rows, data.scores) : []), [data]);
  const rows = status === null ? sorted : sorted.filter((c) => c.status === status);
  const page = rows.slice(offset, offset + PAGE_SIZE);

  function pickStatus(next: string | null) {
    setStatus(next);
    setOffset(0);
  }

  return (
    <div>
      <PageHeader
        title="Hàng đợi case"
        subtitle="Các case của lượt chạy mới nhất. Case có hạng xếp trước theo hạng, các case còn lại theo cảnh báo mới nhất."
      />
      <div className="toolbar">
        <span className="muted" id="case-status-filter">
          Trạng thái
        </span>
        <div className="chip-group" role="group" aria-labelledby="case-status-filter">
          {STATUSES.map((value) => (
            <button
              key={value ?? "all"}
              type="button"
              className="chip"
              aria-pressed={status === value}
              onClick={() => pickStatus(value)}
            >
              {value === null ? "Tất cả" : CASE_STATUS_LABELS[value]}
            </button>
          ))}
        </div>
      </div>
      <section className="panel" aria-busy={state.kind === "loading"}>
        {state.kind === "loading" && (
          <div className="skeleton-stack" role="status">
            <span className="sr-only">Đang tải...</span>
            <span className="skeleton" />
            <span className="skeleton" />
            <span className="skeleton" />
            <span className="skeleton" />
          </div>
        )}
        {state.kind === "error" && (
          <div className="alert alert-danger" role="alert">
            <IconAlert />
            <div>
              <strong className="alert-title">Chưa có dữ liệu</strong>
              <code>{state.code}</code> {errorCodeLabel(state.code)}. {state.message}
            </div>
          </div>
        )}
        {data !== null && (
          <>
            <div className="stat-row">
              <Stat label="Lượt chạy" value={dash(data.runId)} />
              <Stat
                label="Ngày dữ liệu"
                value={formatDate(typeof data.asOf === "string" ? data.asOf : null)}
              />
              <Stat
                label="Số case"
                value={formatNumber(rows.length)}
                hint={status === null ? "Mọi trạng thái" : CASE_STATUS_LABELS[status]}
                tone="info"
              />
            </div>
            <p className="muted">Mô hình chỉ xếp hạng, không đóng case</p>
            {rows.length === 0 ? (
              <EmptyState
                title="Không có case nào"
                hint={
                  data.runId === null || data.runId === undefined ? (
                    <>
                      Chưa có lượt chạy nào. Chạy <code>aml cases build</code> để tạo case.
                    </>
                  ) : (
                    "Không có case nào khớp bộ lọc trạng thái đang chọn."
                  )
                }
              />
            ) : (
              <CaseTable rows={page} scores={data.scores} />
            )}
            {rows.length > 0 && (
              <Pager
                offset={offset}
                limit={PAGE_SIZE}
                total={rows.length}
                shown={page.length}
                onPage={setOffset}
              />
            )}
          </>
        )}
      </section>
    </div>
  );
}
