import { Fragment } from "react";
import ApiPanel from "../components/ApiPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import Stat from "../components/Stat";
import StatusBadge from "../components/StatusBadge";
import type { BenchCell, BenchData, BenchRun } from "../api/benchmarkTypes";
import {
  DASH,
  backendLabel,
  benchMetaLabel,
  benchNote,
  mismatchLine,
  skipReason,
  formatDateTime,
  formatNumber,
  traceMethodLabel,
  yesNo,
} from "../i18n";
import "./benchmark/benchmark.css";

/** Meta values that are identifiers or commands: shown as stored, in mono. */
const CODE_KEYS = new Set(["schema", "profile", "command", "git_commit", "accounts"]);

/** One meta value as stored: numbers keep every digit, nested objects become nested lists. */
function MetaValue({ name, value }: { name: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return <>{DASH}</>;
  if (typeof value === "boolean") return <>{yesNo(value)}</>;
  if (typeof value === "number") return <>{formatNumber(value)}</>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <>{DASH}</>;
    return (
      <>
        {value.map((item, i) => (
          <Fragment key={i}>
            {i > 0 && ", "}
            <MetaValue name={name} value={item} />
          </Fragment>
        ))}
      </>
    );
  }
  if (typeof value === "object") return <MetaList meta={value as Record<string, unknown>} />;
  const text = String(value);
  if (name === "started_at") return <>{formatDateTime(text)}</>;
  if (name === "backend") return <>{backendLabel(text)}</>;
  return CODE_KEYS.has(name) ? <span className="code">{text}</span> : <>{text}</>;
}

/** Text where `backticks` mark a command or field name: those parts are shown as code. */
function WithCode({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, i) => (i % 2 === 1 ? <code key={i}>{part}</code> : part))}
    </>
  );
}

function MetaList({ meta }: { meta: Record<string, unknown> }) {
  return (
    <dl className="kv bench-meta">
      {Object.entries(meta).map(([key, value]) => (
        <div key={key}>
          <dt>{benchMetaLabel(key)}</dt>
          <dd>
            <MetaValue name={key} value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

const KEY_FACTS = ["profile", "backend", "total_seconds", "git_commit"] as const;

function KeyFacts({ meta }: { meta: Record<string, unknown> }) {
  return (
    <div className="stat-row">
      {KEY_FACTS.map((key) => (
        <Stat key={key} label={benchMetaLabel(key)} value={<MetaValue name={key} value={meta[key]} />} />
      ))}
    </div>
  );
}

function cellKey(c: BenchCell): string {
  return `${c.method}|${c.account}|${c.hours}|${c.hops}`;
}

/** Timings are shown exactly as stored (formatNumber keeps every digit); the unit is in the header. */
function CellTable({ cells }: { cells: BenchCell[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Phương pháp</th>
            <th>Tài khoản</th>
            <th className="num">Khung thời gian (giờ)</th>
            <th className="num">Số bước</th>
            <th>Trạng thái</th>
            <th>Kết quả chính xác</th>
            <th className="num">Số lần đo</th>
            <th className="num">Trung vị (ms)</th>
            <th className="num">P95 (ms)</th>
            <th className="num">Nhanh nhất (ms)</th>
            <th className="num">Chậm nhất (ms)</th>
            <th className="num">Số đường đi</th>
            <th className="num">Số tài khoản</th>
            <th className="num">Số chu trình</th>
            <th className="num">Số dòng truy vấn</th>
            <th>Ghi chú</th>
          </tr>
        </thead>
        <tbody>
          {cells.map((c) => (
            <tr key={cellKey(c)}>
              <td>
                {traceMethodLabel(c.method)}
                <code className="cell-sub">{c.method}</code>
              </td>
              <td>
                <span className="code">{c.account}</span>
              </td>
              <td className="num">{formatNumber(c.hours)}</td>
              <td className="num">{formatNumber(c.hops)}</td>
              <td>
                <StatusBadge kind="benchStatus" value={c.status} />
              </td>
              <td>{yesNo(c.exact)}</td>
              <td className="num">{formatNumber(c.runs)}</td>
              <td className="num">{formatNumber(c.median_ms)}</td>
              <td className="num">{formatNumber(c.p95_ms)}</td>
              <td className="num">{formatNumber(c.min_ms)}</td>
              <td className="num">{formatNumber(c.max_ms)}</td>
              <td className="num">{formatNumber(c.n_paths)}</td>
              <td className="num">{formatNumber(c.n_accounts)}</td>
              <td className="num">{formatNumber(c.n_cycles)}</td>
              <td className="num">{formatNumber(c.query_lines)}</td>
              <td className="wrap">{skipReason(c.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunCard({ run }: { run: BenchRun }) {
  return (
    <article className="panel">
      <div className="panel-header">
        <h2>
          Tệp kết quả <span className="code">{run.file}</span>
        </h2>
      </div>
      <KeyFacts meta={run.meta} />
      {run.mismatches.length > 0 && (
        <div className="alert alert-warning" role="alert">
          <div>
            <strong className="alert-title">
              Số đường đi giữa các phương pháp chính xác không khớp
            </strong>
            <ul className="bench-list">
              {run.mismatches.map((m) => (
                <li key={m}>{mismatchLine(m)}</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <CellTable cells={run.cells} />
      <details className="bench-details">
        <summary>Toàn bộ thông tin lần đo</summary>
        <MetaList meta={run.meta} />
      </details>
    </article>
  );
}

export default function BenchmarkPage() {
  return (
    <>
      <PageHeader
        title="Đối chiếu phương pháp truy vết"
        subtitle="Thời gian truy vết dòng tiền của từng phương pháp, đọc nguyên văn từ các tệp kết quả của lệnh đo."
      />
      <ApiPanel<BenchData> path="/benchmark">
        {(data) =>
          data.runs.length === 0 ? (
            <EmptyState
              title="Chưa có kết quả đo"
              hint={
                <>
                  Chưa chạy <code>aml bench</code>
                </>
              }
            />
          ) : (
            <>
              {data.runs.map((run) => (
                <RunCard key={run.file} run={run} />
              ))}
              <section className="panel">
                <h2>Ghi chú về phép đo</h2>
                <ul className="bench-list">
                  {data.notes.map((n) => (
                    <li key={n}>
                      <WithCode text={benchNote(n)} />
                    </li>
                  ))}
                </ul>
              </section>
            </>
          )
        }
      </ApiPanel>
    </>
  );
}
