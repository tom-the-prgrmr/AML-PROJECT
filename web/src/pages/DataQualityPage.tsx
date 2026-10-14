import { useEffect, useState } from "react";
import ApiPanel from "../components/ApiPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import RuleLabel from "../components/RuleLabel";
import Stat from "../components/Stat";
import StatusBadge from "../components/StatusBadge";
import type { DqResult, DqResultsMeta, DqTrendMeta, DqTrendPoint } from "../api/dqTypes";
import {
  DASH,
  dqDimensionLabel,
  dqScopeLabel,
  dqStatusLabel,
  formatDate,
  formatDateTime,
  formatNumber,
  ruleDescription,
  ruleName,
  tableLabel,
} from "../i18n";
import "./dq/dq.css";

/** How many sample ids a row shows before the "+N nữa" expander. */
const SAMPLE_IDS_SHOWN = 3;

function NotRun() {
  return (
    <EmptyState
      title="Chưa có kết quả kiểm tra chất lượng dữ liệu"
      hint={
        <>
          Chưa chạy <code>aml dq run</code>
        </>
      }
    />
  );
}

/**
 * A ratio as a percentage with every stored digit: the decimal point of the number's own text
 * moves two places, so nothing is computed or rounded (0.019608 -> "1,9608%").
 */
function exactPercent(ratio: number | null): string {
  if (ratio === null) return DASH;
  const m = /^(\d+)(?:\.(\d+))?$/.exec(String(ratio));
  if (!m) return formatNumber(ratio); // exponent form or negative: show the raw ratio
  const digits = m[1] + (m[2] ?? "").padEnd(2, "0");
  const cut = m[1].length + 2;
  const whole = digits.slice(0, cut).replace(/^0+(?=\d)/, "");
  const fraction = digits.slice(cut);
  return `${whole}${fraction ? `,${fraction}` : ""}%`;
}

/** Change of the failed rows against the previous run; "—" when there is no previous run. */
function Delta({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="muted">{DASH}</span>;
  if (delta > 0) return <span className="dq-delta-up">↑ +{formatNumber(delta)}</span>;
  if (delta < 0) return <span className="dq-delta-down">↓ {formatNumber(delta)}</span>;
  return <span>{formatNumber(delta)}</span>;
}

function IdList({ ids }: { ids: (string | number)[] }) {
  return (
    <>
      {ids.map((id, i) => (
        <span key={`${id}-${i}`}>
          {i > 0 && ", "}
          <span className="code">{String(id)}</span>
        </span>
      ))}
    </>
  );
}

/** The first few sample ids; the rest stay reachable behind an expander. */
function SampleIds({ ids }: { ids: (string | number)[] }) {
  if (ids.length === 0) return <span className="muted">{DASH}</span>;
  const rest = ids.slice(SAMPLE_IDS_SHOWN);
  return (
    <>
      <IdList ids={ids.slice(0, SAMPLE_IDS_SHOWN)} />
      {rest.length > 0 && (
        <details className="dq-more">
          <summary>+{formatNumber(rest.length)} nữa</summary>
          <div className="dq-more-box">
            <IdList ids={rest} />
          </div>
        </details>
      )}
    </>
  );
}

function Summary({ meta }: { meta: DqResultsMeta }) {
  return (
    <div className="stat-row">
      <Stat label="Số luật" value={formatNumber(meta.rules)} />
      <Stat label="Đạt" value={formatNumber(meta.passed)} tone="success" />
      <Stat label="Không đạt" value={formatNumber(meta.failed)} tone="danger" />
      <Stat label="Không có dữ liệu" value={formatNumber(meta.no_data)} />
    </div>
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
            <th>Tiêu chí</th>
            <th>Phạm vi</th>
            <th>Mô tả</th>
            <th className="num">Ngưỡng tỷ lệ lỗi</th>
            <th className="num">Tổng số dòng</th>
            <th className="num">Số dòng lỗi</th>
            <th className="num">Tỷ lệ lỗi</th>
            <th>Trạng thái</th>
            <th className="num">Dòng lỗi lần trước</th>
            <th className="num">Thay đổi</th>
            <th>Mã mẫu bị lỗi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.rule_id}>
              <td>
                <RuleLabel id={r.rule_id} />
              </td>
              <td>{tableLabel(r.table_name)}</td>
              <td>{dqDimensionLabel(r.dimension)}</td>
              <td>{dqScopeLabel(r.scope)}</td>
              <td className="dq-desc">{ruleDescription(r.rule_id, r.description)}</td>
              <td className="num">{exactPercent(r.max_fail_rate)}</td>
              <td className="num">{formatNumber(r.total_rows)}</td>
              <td className="num">{formatNumber(r.failed_rows)}</td>
              <td className="num">{exactPercent(r.fail_rate)}</td>
              <td>
                <StatusBadge kind="dqStatus" value={r.status} />
              </td>
              <td className="num">{formatNumber(r.prev_failed_rows)}</td>
              <td className="num">
                <Delta delta={r.delta_failed_rows} />
              </td>
              <td className="dq-ids">
                <SampleIds ids={r.sample_ids} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One bar per run: the failed rows above it, the run number below it. */
function RuleTrend({ points }: { points: DqTrendPoint[] }) {
  const top = Math.max(...points.map((p) => p.failed_rows), 1);
  return (
    <div className="dq-trend">
      {points.map((p) => (
        <div
          key={p.run_id}
          className="dq-bar-slot"
          title={`Lần chạy ${p.run_id}: ${formatNumber(p.failed_rows)} dòng lỗi (${dqStatusLabel(p.status)})`}
        >
          <span className="dq-bar-value">{formatNumber(p.failed_rows)}</span>
          <div className="dq-bar-track">
            <div
              className={p.status === "FAIL" ? "dq-bar dq-bar-fail" : "dq-bar"}
              style={{ height: `${(p.failed_rows / top) * 100}%` }}
            />
          </div>
          <span className="dq-bar-run">Lần {p.run_id}</span>
        </div>
      ))}
    </div>
  );
}

function TrendTable({ points }: { points: DqTrendPoint[] }) {
  const [rule, setRule] = useState("");
  const all = new Map<string, DqTrendPoint[]>();
  for (const p of points) all.set(p.rule_id, [...(all.get(p.rule_id) ?? []), p]);
  const byRule = rule === "" ? all : new Map([[rule, all.get(rule) ?? []]]);
  return (
    <>
      <label className="toolbar">
        <span>Luật</span>
        <select aria-label="Chọn luật" value={rule} onChange={(e) => setRule(e.target.value)}>
          <option value="">Tất cả luật</option>
          {[...all.keys()].map((id) => (
            <option key={id} value={id}>
              {ruleName(id)}
            </option>
          ))}
        </select>
      </label>
      <p className="dq-legend">
        <span className="dq-swatch dq-bar-fail" /> Lần chạy không đạt
        <span className="dq-swatch" /> Lần chạy đạt hoặc không có dữ liệu
        <span>
          Số trên mỗi cột là số dòng lỗi. Chiều cao cột được tính riêng theo giá trị lớn nhất của
          từng luật, nên không so sánh được giữa các luật.
        </span>
      </p>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Luật</th>
              <th>Số dòng lỗi theo lần chạy</th>
            </tr>
          </thead>
          <tbody>
            {[...byRule.entries()].map(([ruleId, series]) => (
              <tr key={ruleId}>
                <td>
                  <RuleLabel id={ruleId} />
                </td>
                <td>
                  <RuleTrend points={series} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Hands the run summary to the page so the header above the panel can show it. */
function RunInfo({ meta, onMeta }: { meta: DqResultsMeta; onMeta: (m: DqResultsMeta) => void }) {
  useEffect(() => onMeta(meta), [meta, onMeta]);
  return null;
}

function runLine(run: DqResultsMeta | null): string {
  if (run === null || run.run_id === null) return "Kết quả các luật kiểm tra của lần chạy mới nhất.";
  return (
    `Lần chạy ${run.run_id} · Ngày dữ liệu ${formatDate(run.as_of)} · ` +
    `Thời điểm chạy ${formatDateTime(run.run_ts)} (UTC)`
  );
}

export default function DataQualityPage() {
  const [run, setRun] = useState<DqResultsMeta | null>(null);
  return (
    <>
      <PageHeader title="Chất lượng dữ liệu" subtitle={runLine(run)} />
      <ApiPanel<DqResult[]> path="/dq/results">
        {(rows, meta) =>
          rows.length === 0 ? (
            <NotRun />
          ) : (
            <>
              <RunInfo meta={meta as unknown as DqResultsMeta} onMeta={setRun} />
              <Summary meta={meta as unknown as DqResultsMeta} />
              <section className="panel">
                <h2>Kết quả theo luật</h2>
                <RuleTable rows={rows} />
              </section>
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
