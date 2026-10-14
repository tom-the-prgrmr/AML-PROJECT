import { useState } from "react";
import { Link } from "react-router-dom";
import type { CaseRow } from "../api/types";
import ApiPanel from "../components/ApiPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import Pager from "../components/Pager";
import Stat from "../components/Stat";
import StatusBadge from "../components/StatusBadge";
import { CASE_STATUS_LABELS, dash, formatDate, formatDateTime, formatNumber } from "../i18n";
import "./case/overview.css";

/** The filter values the endpoint accepts; null is "every status". */
const STATUSES: (string | null)[] = [null, ...Object.keys(CASE_STATUS_LABELS)];

function casesPath(status: string | null, offset: number): string {
  const query = new URLSearchParams();
  if (status !== null) query.set("status", status);
  if (offset > 0) query.set("offset", String(offset));
  const text = query.toString();
  return text === "" ? "/cases" : `/cases?${text}`;
}

function CaseTable({ rows }: { rows: CaseRow[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Mã case</th>
            <th>Khách hàng gộp</th>
            <th>Trạng thái</th>
            <th>Quyết định</th>
            <th>Nguồn cảnh báo</th>
            <th className="num">Số cảnh báo</th>
            <th>Cảnh báo gần nhất</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.case_id}>
              <td>
                <Link className="code nowrap" to={`/cases/${c.case_id}`}>
                  {c.case_id}
                </Link>
              </td>
              <td className="code">{c.golden_customer_id}</td>
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
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CasesPage() {
  const [status, setStatus] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  function pickStatus(next: string | null) {
    setStatus(next);
    setOffset(0);
  }

  return (
    <div>
      <PageHeader
        title="Hàng đợi case"
        subtitle="Các case của lượt chạy mới nhất, case có cảnh báo mới nhất xếp trước."
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
      <ApiPanel<CaseRow[]> path={casesPath(status, offset)}>
        {(rows, meta) => {
          const total = Number(meta.total ?? rows.length);
          return (
            <>
              <div className="stat-row">
                <Stat label="Lượt chạy" value={dash(meta.run_id)} />
                <Stat
                  label="Ngày dữ liệu"
                  value={formatDate(typeof meta.as_of === "string" ? meta.as_of : null)}
                />
                <Stat
                  label="Số case"
                  value={formatNumber(total)}
                  hint={status === null ? "Mọi trạng thái" : CASE_STATUS_LABELS[status]}
                  tone="info"
                />
              </div>
              {rows.length === 0 ? (
                <EmptyState
                  title="Không có case nào"
                  hint={
                    meta.run_id === null || meta.run_id === undefined ? (
                      <>
                        Chưa có lượt chạy nào. Chạy <code>aml cases build</code> để tạo case.
                      </>
                    ) : (
                      "Không có case nào khớp bộ lọc trạng thái đang chọn."
                    )
                  }
                />
              ) : (
                <CaseTable rows={rows} />
              )}
              {total > 0 && (
                <Pager
                  offset={Number(meta.offset ?? 0)}
                  limit={Number(meta.limit ?? rows.length)}
                  total={total}
                  shown={rows.length}
                  onPage={setOffset}
                />
              )}
            </>
          );
        }}
      </ApiPanel>
    </div>
  );
}
