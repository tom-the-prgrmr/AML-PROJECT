import type { SuppressionMetrics } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import RuleLabel from "../../components/RuleLabel";
import Stat from "../../components/Stat";
import StatusBadge from "../../components/StatusBadge";
import { dash, formatDate, formatNumber, suppressionRuleLabel, truthLabel } from "../../i18n";
import { StageTable, UnavailableList } from "./FunnelPanel";
import "./metrics.css";

function Body({ m }: { m: SuppressionMetrics }) {
  return (
    <>
      <p className="muted">
        {m.case_run === null
          ? "Chưa có lần chạy case nào."
          : `Lần chạy case số ${m.case_run.run_id}, dữ liệu tính đến ngày ${formatDate(m.case_run.as_of)}.`}
      </p>
      <UnavailableList rows={m.unavailable} />
      {m.stage !== null && <StageTable stages={[m.stage]} minutes={m.minutes_per_alert} />}
      <div className="stat-row">
        <Stat label="Mục bị loại trừ" value={formatNumber(m.population)} />
        {m.by_rule !== null &&
          Object.entries(m.by_rule).map(([rule, n]) => (
            <Stat key={rule} label={suppressionRuleLabel(rule)} value={formatNumber(n)} />
          ))}
        <Stat
          label="Mục đáng ngờ bị loại trừ"
          value={dash(m.suspicious_suppressed)}
          hint={m.ground_truth_available ? "Theo ground truth, trên toàn bộ" : "Chưa có ground truth"}
          tone={m.suspicious_suppressed ? "danger" : undefined}
        />
        <Stat label="Hạt giống chọn mẫu (seed)" value={formatNumber(m.seed)} />
        <Stat label="Cỡ mẫu" value={formatNumber(m.sample_size)} />
      </div>
      {m.sample.length === 0 ? (
        <EmptyState title="Không có mục nào bị loại trừ" />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Mục cảnh báo</th>
                <th>Khách hàng gộp</th>
                <th>Nguồn</th>
                <th>Luật phát hiện</th>
                <th>Luật loại trừ</th>
                <th>Lý do loại trừ</th>
                <th>Theo ground truth</th>
              </tr>
            </thead>
            <tbody>
              {m.sample.map((r) => (
                <tr key={`${r.item_key}:${r.golden_customer_id}`}>
                  <td className="code wrap">{r.item_key}</td>
                  <td className="code">{r.golden_customer_id}</td>
                  <td>
                    <StatusBadge kind="source" value={r.source} />
                  </td>
                  <td>
                    <RuleLabel id={r.rule_id} />
                  </td>
                  <td>{suppressionRuleLabel(r.suppression_rule)}</td>
                  <td className="wrap">{r.suppression_reason}</td>
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

export default function SuppressionPanel() {
  return (
    <ApiPanel<SuppressionMetrics> path="/metrics/suppression" title="Loại trừ cảnh báo (good-guy, ngủ đông)">
      {(m) => <Body m={m} />}
    </ApiPanel>
  );
}
