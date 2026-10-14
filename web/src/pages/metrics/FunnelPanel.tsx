import type { Funnel, OriginCount, Stage, Unavailable } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import Stat from "../../components/Stat";
import { dash, formatDate, formatNumber, formatPercent, metricPartLabel, stageLabel, stageUnitLabel } from "../../i18n";
import "./metrics.css";

/** Parts that could not be computed: the part in Vietnamese, then the server's own message. */
export function UnavailableList({ rows }: { rows: Unavailable[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="alert alert-warning" role="status">
      <ul className="metrics-unavailable">
        {rows.map((u, i) => (
          <li key={`${u.part}-${i}`}>
            <strong>{metricPartLabel(u.part)}</strong>: {u.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Hours are an estimate; the assumption always sits next to the figure. */
export function HoursCell({ hours, minutes }: { hours: number | null; minutes: number }) {
  return (
    <>
      {hours === null ? dash(hours) : `${formatNumber(hours)} giờ (ước tính)`}
      <span className="cell-sub">Giả định: {formatNumber(minutes)} phút / alert</span>
    </>
  );
}

export function StageTable({ stages, minutes }: { stages: Stage[]; minutes: number }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Công cụ</th>
            <th>Đơn vị đếm</th>
            <th className="num">Trước</th>
            <th className="num">Sau</th>
            <th className="num">Giảm</th>
            <th className="num">Giảm (%)</th>
            <th>Giờ tiết kiệm</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((s) => (
            <tr key={s.tool}>
              <td>{stageLabel(s.tool)}</td>
              <td>
                {stageUnitLabel(s.before_label)} → {stageUnitLabel(s.after_label)}
              </td>
              <td className="num">{formatNumber(s.before)}</td>
              <td className="num">{formatNumber(s.after)}</td>
              <td className="num">{formatNumber(s.removed)}</td>
              <td className="num">{s.reduction_pct === null ? dash(null) : `${formatNumber(s.reduction_pct)}%`}</td>
              <td>
                <HoursCell hours={s.hours_saved} minutes={minutes} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Decisions({ title, c }: { title: string; c: OriginCount }) {
  return (
    <div className="metrics-origin">
      <h4>{title}</h4>
      <div className="stat-row">
        <Stat label="Đã quyết định" value={formatNumber(c.decided)} />
        <Stat label="Đáng ngờ" value={formatNumber(c.suspicious)} />
        <Stat label="Báo động giả" value={formatNumber(c.false_positive)} />
      </div>
    </div>
  );
}

function FunnelBody({ funnel }: { funnel: Funnel }) {
  const { alert_to_case: a, case_to_suspicious: c } = funnel.conversion;
  const human = c.by_origin.HUMAN ?? { decided: 0, suspicious: 0, false_positive: 0 };
  const simulated = c.by_origin.SIMULATED ?? { decided: 0, suspicious: 0, false_positive: 0 };
  return (
    <>
      <p className="muted">
        {funnel.case_run === null
          ? "Chưa có lần chạy case nào."
          : `Lần chạy case số ${funnel.case_run.run_id}, dữ liệu tính đến ngày ${formatDate(funnel.case_run.as_of)}.`}
      </p>
      <UnavailableList rows={funnel.unavailable} />
      <StageTable stages={funnel.stages} minutes={funnel.minutes_per_alert} />
      <p className="metrics-note">
        Tổng giờ tiết kiệm của các bước tính được (ước tính):{" "}
        <strong>{funnel.total_hours_saved === null ? dash(null) : `${formatNumber(funnel.total_hours_saved)} giờ`}</strong>
        . Giả định: {formatNumber(funnel.minutes_per_alert)} phút / alert.
      </p>
      <h3>Từ cảnh báo đến case</h3>
      <div className="stat-row">
        <Stat label="Cảnh báo phân biệt" value={formatNumber(a.alerts)} />
        <Stat label="Mục cảnh báo (cảnh báo × khách hàng gộp)" value={formatNumber(a.items)} />
        <Stat label="Case" value={formatNumber(a.cases)} />
        <Stat label="Case trên mỗi cảnh báo" value={a.cases_per_alert === null ? dash(null) : formatNumber(a.cases_per_alert)} />
      </div>
      <h3>Từ case đến đáng ngờ</h3>
      <p className="muted">
        Tỷ lệ đáng ngờ trên các case đã có quyết định: <strong>{formatPercent(c.rate)}</strong> (
        {formatNumber(c.suspicious)} / {formatNumber(c.decided)}). Hai nguồn quyết định được tách riêng.
      </p>
      <div className="metrics-origins">
        <Decisions title="Người quyết định" c={human} />
        <Decisions title="Mô phỏng từ ground truth" c={simulated} />
      </div>
    </>
  );
}

export default function FunnelPanel() {
  return (
    <ApiPanel<Funnel> path="/metrics/funnel" title="Phễu giảm tải">
      {(funnel) => <FunnelBody funnel={funnel} />}
    </ApiPanel>
  );
}
