import { useState } from "react";
import type { Hit, HitsMeta, SystemDecision } from "../api/screeningTypes";
import ApiPanel from "../components/ApiPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import Pager from "../components/Pager";
import Stat from "../components/Stat";
import type { Tone } from "../components/tone";
import { formatDate, formatNumber, piiLabel, screeningDecisionLabel } from "../i18n";
import HitRow from "./screening/HitRow";
import "./screening/screening.css";

const DECISIONS: SystemDecision[] = ["ALERT", "REVIEW", "AUTO_CLEARED"];

const DECISION_TONE: Record<SystemDecision, Tone> = {
  ALERT: "danger",
  REVIEW: "warning",
  AUTO_CLEARED: "success",
};

/** Which run the page shows, and whether personal data is masked for the current user. */
function subtitle(meta: HitsMeta): string {
  const run =
    meta.run_id === null
      ? "Chưa có lần chạy sàng lọc nào"
      : `Lần chạy sàng lọc số ${meta.run_id}, dữ liệu tính đến ngày ${formatDate(meta.as_of)}`;
  return `${run}. ${piiLabel(meta.pii)}.`;
}

export default function ScreeningPage() {
  const [filter, setFilterValue] = useState<SystemDecision | null>(null);
  const [offset, setOffset] = useState(0);
  const setFilter = (value: SystemDecision | null) => {
    setFilterValue(value);
    setOffset(0);
  };
  const path = `/screening/hits?offset=${offset}` + (filter ? `&decision=${filter}` : "");
  return (
    <ApiPanel<Hit[]> path={path}>
      {(hits, rawMeta, reload) => {
        const meta = rawMeta as unknown as HitsMeta;
        return (
          <>
            <PageHeader title="Rà soát sàng lọc danh sách" subtitle={subtitle(meta)} />
            <div className="stat-row">
              {DECISIONS.map((d) => (
                <Stat
                  key={d}
                  label={screeningDecisionLabel(d)}
                  value={formatNumber(meta.counts[d])}
                  hint="cặp khách hàng và mục danh sách"
                  tone={DECISION_TONE[d]}
                />
              ))}
              <Stat
                label="Ngưỡng cảnh báo"
                value={`≥ ${formatNumber(meta.thresholds.alert)}`}
                hint="Điểm cuối từ mức này trở lên"
              />
              <Stat
                label="Ngưỡng rà soát"
                value={`≥ ${formatNumber(meta.thresholds.review)}`}
                hint="Điểm cuối từ mức này trở lên"
              />
            </div>
            <section className="panel">
              <div className="panel-header">
                <h2>Các cặp khớp tên</h2>
                <div
                  className="chip-group"
                  role="group"
                  aria-label="Lọc theo quyết định của hệ thống"
                >
                  <button
                    type="button"
                    className="chip"
                    aria-pressed={filter === null}
                    onClick={() => setFilter(null)}
                  >
                    Tất cả
                  </button>
                  {DECISIONS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      className="chip"
                      aria-pressed={filter === d}
                      onClick={() => setFilter(d)}
                    >
                      {screeningDecisionLabel(d)} ({formatNumber(meta.counts[d])})
                    </button>
                  ))}
                </div>
              </div>
              <div className="alert alert-info">
                <div>
                  Quyết định của chuyên viên đứng cạnh quyết định của hệ thống và không thay thế nó.
                  Nó chỉ được ghi vào nhật ký kiểm toán (<span className="code">audit_log</span>),
                  không đóng, không loại và không nộp bất cứ thứ gì.
                </div>
              </div>
              {hits.length === 0 ? (
                <EmptyState
                  title="Không có cặp khớp nào"
                  hint="Hãy chọn bộ lọc khác hoặc chạy lại bước sàng lọc."
                />
              ) : (
                <div className="table-wrap">
                  <table className="data screening-table">
                    <thead>
                      <tr>
                        <th>Khách hàng</th>
                        <th>Tên trong danh sách</th>
                        <th>So khớp tên (tầng 1)</th>
                        <th>Điểm tên và định danh (tầng 2)</th>
                        <th className="num">Điểm cuối</th>
                        <th>Quyết định của hệ thống</th>
                        <th>Rà soát của chuyên viên</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hits.map((h) => (
                        <HitRow key={`${h.cif}:${h.entry_id}`} hit={h} onRecorded={reload} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Pager
                offset={meta.offset}
                limit={meta.limit}
                total={meta.total}
                shown={hits.length}
                onPage={setOffset}
              />
            </section>
          </>
        );
      }}
    </ApiPanel>
  );
}
