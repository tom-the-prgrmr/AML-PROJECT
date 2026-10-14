import ApiPanel from "../components/ApiPanel";
import type {
  DqResult,
  DqResultsMeta,
  DqTrendMeta,
  DqTrendPoint,
} from "../api/dqTypes";
import "./dq/dq.css";

function NotRun() {
  return (
    <p className="muted">
      Chưa chạy <code>aml dq run</code>
    </p>
  );
}

function Delta({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="muted">-</span>;
  if (delta > 0) return <span className="dq-delta-up">▲ +{delta}</span>;
  if (delta < 0) return <span className="dq-delta-down">▼ {delta}</span>;
  return <span>= 0</span>;
}

function Summary({ meta }: { meta: DqResultsMeta }) {
  return (
    <dl className="dq-summary">
      <div>Lần chạy: <strong>{meta.run_id}</strong></div>
      <div>Ngày dữ liệu: <strong>{meta.as_of}</strong></div>
      <div>Thời điểm chạy (UTC): <strong>{meta.run_ts}</strong></div>
      <div>Số luật: <strong>{meta.rules}</strong></div>
      <div>Đạt: <strong>{meta.passed}</strong></div>
      <div>Không đạt: <strong>{meta.failed}</strong></div>
      <div>Không có dữ liệu: <strong>{meta.no_data}</strong></div>
    </dl>
  );
}

function RuleTable({ rows }: { rows: DqResult[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Luật</th>
            <th>Bảng</th>
            <th>Chiều</th>
            <th>Phạm vi</th>
            <th>Mô tả</th>
            <th>Ngưỡng</th>
            <th>Tổng dòng</th>
            <th>Dòng lỗi</th>
            <th>Tỷ lệ lỗi</th>
            <th>Trạng thái</th>
            <th>Lần trước</th>
            <th>Thay đổi</th>
            <th>Mẫu lỗi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rule_id}>
              <td>{r.rule_id}</td>
              <td>{r.table_name}</td>
              <td>{r.dimension}</td>
              <td>{r.scope}</td>
              <td>{r.description}</td>
              <td>{r.max_fail_rate}</td>
              <td>{r.total_rows}</td>
              <td>{r.failed_rows}</td>
              <td>{r.fail_rate ?? "-"}</td>
              <td>{r.status}</td>
              <td>{r.prev_failed_rows ?? "-"}</td>
              <td><Delta delta={r.delta_failed_rows} /></td>
              <td className="dq-ids">{r.sample_ids.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RuleTrend({ points }: { points: DqTrendPoint[] }) {
  const top = Math.max(...points.map((p) => p.failed_rows), 1);
  return (
    <div className="dq-trend-box">
      <div className="dq-trend">
        {points.map((p) => (
          <div
            key={p.run_id}
            className={p.status === "PASS" ? "dq-bar pass" : "dq-bar"}
            style={{ height: `${(p.failed_rows / top) * 100}%` }}
            title={`Lần ${p.run_id}: ${p.failed_rows} dòng lỗi (${p.status})`}
          >
            <span className="dq-bar-label">{p.failed_rows}</span>
            <span className="dq-bar-run">{p.run_id}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendTable({ points }: { points: DqTrendPoint[] }) {
  const byRule = new Map<string, DqTrendPoint[]>();
  for (const p of points) byRule.set(p.rule_id, [...(byRule.get(p.rule_id) ?? []), p]);
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Luật</th>
          <th>Số dòng lỗi theo lần chạy (chiều cao cột tính theo từng luật)</th>
        </tr>
      </thead>
      <tbody>
        {[...byRule.entries()].map(([ruleId, series]) => (
          <tr key={ruleId}>
            <td>{ruleId}</td>
            <td><RuleTrend points={series} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DataQualityPage() {
  return (
    <>
      <ApiPanel<DqResult[]> path="/dq/results" title="Chất lượng dữ liệu">
        {(rows, meta) =>
          rows.length === 0 ? (
            <NotRun />
          ) : (
            <>
              <Summary meta={meta as unknown as DqResultsMeta} />
              <RuleTable rows={rows} />
            </>
          )
        }
      </ApiPanel>
      <ApiPanel<DqTrendPoint[]> path="/dq/trend" title="Xu hướng theo luật">
        {(points, meta) =>
          points.length === 0 ? (
            <NotRun />
          ) : (
            <>
              <p className="muted">
                Các lần chạy: {(meta as unknown as DqTrendMeta).runs.join(", ")}
              </p>
              <TrendTable points={points} />
            </>
          )
        }
      </ApiPanel>
    </>
  );
}

