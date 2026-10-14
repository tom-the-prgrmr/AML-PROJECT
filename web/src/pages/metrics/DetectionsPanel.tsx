import type { DetectionRow, Detections } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import RuleLabel from "../../components/RuleLabel";
import StatusBadge from "../../components/StatusBadge";
import { dash, formatNumber, formatPercent, screeningMethodLabel, typologyLabel } from "../../i18n";
import { UnavailableList } from "./FunnelPanel";
import "./metrics.css";

const count = (n: number | null) => formatNumber(n);

function DetectionTable({ rows }: { rows: DetectionRow[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Nguồn</th>
            <th>Phát hiện</th>
            <th>Kiểu hành vi mục tiêu</th>
            <th className="num">Cảnh báo</th>
            <th className="num">Đúng</th>
            <th className="num">Sai</th>
            <th className="num">Tỷ lệ sai</th>
            <th className="num">Độ chính xác</th>
            <th className="num">Độ phủ</th>
            <th className="num">Kịch bản</th>
            <th className="num">Bắt được</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.source}-${r.detection}`}>
              <td>
                <StatusBadge kind="source" value={r.source} />
              </td>
              <td>{r.source === "SCREENING" ? <>{screeningMethodLabel(r.detection)}<code className="cell-sub">{r.detection}</code></> : <RuleLabel id={r.detection} />}</td>
              <td>{r.target_typology ? typologyLabel(r.target_typology) : dash(null)}</td>
              <td className="num">{count(r.alerts)}</td>
              <td className="num">{count(r.true_positives)}</td>
              <td className="num">{count(r.false_positives)}</td>
              <td className="num">{formatPercent(r.fp_rate)}</td>
              <td className="num">{formatPercent(r.precision)}</td>
              <td className="num">{formatPercent(r.recall)}</td>
              <td className="num">{count(r.scenarios)}</td>
              <td className="num">{count(r.detected)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DetectionsPanel() {
  return (
    <ApiPanel<Detections> path="/metrics/detections" title="Chất lượng phát hiện">
      {(data) => {
        const main = data.rows.filter((r) => !r.baseline);
        const baseline = data.rows.filter((r) => r.baseline);
        return (
          <>
            <UnavailableList rows={data.unavailable} />
            {data.rows.length === 0 ? (
              <EmptyState title="Chưa có số liệu phát hiện" />
            ) : (
              <>
                {main.length > 0 && <DetectionTable rows={main} />}
                {baseline.length > 0 && (
                  <>
                    <h3>Đường cơ sở để so sánh</h3>
                    <DetectionTable rows={baseline} />
                  </>
                )}
              </>
            )}
          </>
        );
      }}
    </ApiPanel>
  );
}
