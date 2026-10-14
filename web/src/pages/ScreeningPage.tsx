import { useState } from "react";
import type { Hit, HitsMeta, SystemDecision } from "../api/screeningTypes";
import ApiPanel from "../components/ApiPanel";
import Pager from "../components/Pager";
import HitRow from "./screening/HitRow";
import "./screening/screening.css";

const DECISIONS: SystemDecision[] = ["ALERT", "REVIEW", "AUTO_CLEARED"];

export default function ScreeningPage() {
  const [filter, setFilterValue] = useState<SystemDecision | null>(null);
  const [offset, setOffset] = useState(0);
  const setFilter = (value: SystemDecision | null) => {
    setFilterValue(value);
    setOffset(0);
  };
  const path = `/screening/hits?offset=${offset}` + (filter ? `&decision=${filter}` : "");
  return (
    <div>
      <h2>Rà soát screening</h2>
      <ApiPanel<Hit[]> path={path}>
        {(hits, rawMeta, reload) => {
          const meta = rawMeta as unknown as HitsMeta;
          return (
            <div>
              <div className="toolbar screening-filter">
                <span>
                  <button type="button" aria-pressed={filter === null} onClick={() => setFilter(null)}>
                    Tất cả
                  </button>
                  {DECISIONS.map((d) => (
                    <button
                      key={d}
                      type="button"
                      aria-pressed={filter === d}
                      onClick={() => setFilter(d)}
                    >
                      {d} ({meta.counts[d]})
                    </button>
                  ))}
                </span>
                <span className="muted">
                  Ngưỡng: ALERT &ge; {meta.thresholds.alert}, REVIEW &ge; {meta.thresholds.review}
                  {meta.run_id !== null && ` - lần chạy ${meta.run_id} (${meta.as_of})`}
                </span>
              </div>
              <p className="muted screening-note">
                Quyết định của người đứng cạnh quyết định của hệ thống và không thay thế nó; nó chỉ
                ghi vào audit_log, không đóng, xoá hay nộp gì cả.
              </p>
              {hits.length === 0 ? (
                <p className="muted">Không có hit nào</p>
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Khách hàng</th>
                        <th>Tên trong danh sách</th>
                        <th>Vì sao (Tier 1)</th>
                        <th>Vì sao (Tier 2)</th>
                        <th>Điểm</th>
                        <th>Hệ thống / case</th>
                        <th>Quyết định của người</th>
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
            </div>
          );
        }}
      </ApiPanel>
    </div>
  );
}
