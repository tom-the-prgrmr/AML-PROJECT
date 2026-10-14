import type { AutoClearedMetrics } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import Stat from "../../components/Stat";
import { dash, formatNumber, listTypeLabel, truthLabel } from "../../i18n";
import "./metrics.css";

function Body({ m }: { m: AutoClearedMetrics }) {
  return (
    <>
      <div className="stat-row">
        <Stat label="Cặp tự động loại" value={formatNumber(m.population)} />
        <Stat label="Hạt giống chọn mẫu (seed)" value={formatNumber(m.seed)} />
        <Stat label="Cỡ mẫu" value={formatNumber(m.sample_size)} />
        <Stat label="Khớp thật trong toàn bộ" value={dash(m.true_hits_in_population)} />
        <Stat label="Khớp thật trong mẫu" value={dash(m.true_hits_in_sample)} />
      </div>
      {!m.ground_truth_available && (
        <p className="muted">Chưa có ground truth nên chưa gắn nhãn khớp thật cho mẫu.</p>
      )}
      {m.sample.length === 0 ? (
        <EmptyState title="Không có cặp nào bị tự động loại" />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Khách hàng</th>
                <th>Mục danh sách</th>
                <th>Loại danh sách</th>
                <th className="num">Điểm cuối</th>
                <th>Lý do</th>
                <th>Theo ground truth</th>
              </tr>
            </thead>
            <tbody>
              {m.sample.map((r) => (
                <tr key={`${r.cif}:${r.entry_id}`}>
                  <td className="code">{r.cif}</td>
                  <td className="code">{r.entry_id}</td>
                  <td>{listTypeLabel(r.list_type)}</td>
                  <td className="num">{formatNumber(r.final_score)}</td>
                  <td className="wrap">{r.reason}</td>
                  <td>{truthLabel(r.truth)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function AutoClearedPanel() {
  return (
    <ApiPanel<AutoClearedMetrics> path="/metrics/below-the-line/auto-cleared" title="Mẫu các cặp bị tự động loại">
      {(m) => <Body m={m} />}
    </ApiPanel>
  );
}
