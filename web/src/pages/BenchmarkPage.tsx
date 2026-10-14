import ApiPanel from "../components/ApiPanel";
import type { BenchCell, BenchData, BenchRun } from "../api/benchmarkTypes";
import "./benchmark/benchmark.css";

// Nested meta values (versions, machine, dataset, ...) are shown as their stored JSON.
const show = (value: unknown): string => {
  if (value === null || value === undefined) return "-";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
};

function Meta({ meta }: { meta: Record<string, unknown> }) {
  return (
    <dl className="bench-meta">
      {Object.entries(meta).map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd>{show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function cellKey(c: BenchCell): string {
  return `${c.method}|${c.account}|${c.hours}|${c.hops}`;
}

function CellTable({ cells }: { cells: BenchCell[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Phương pháp</th>
            <th>Tài khoản</th>
            <th>T (giờ)</th>
            <th>Số bước</th>
            <th>Trạng thái</th>
            <th>Ghi chú</th>
            <th>Chính xác</th>
            <th>Số lần chạy</th>
            <th>Median (ms)</th>
            <th>P95 (ms)</th>
            <th>Min (ms)</th>
            <th>Max (ms)</th>
            <th>Số đường đi</th>
            <th>Số tài khoản</th>
            <th>Số chu trình</th>
            <th>Số dòng truy vấn</th>
          </tr>
        </thead>
        <tbody>
          {cells.map((c) => (
            <tr key={cellKey(c)}>
              <td>{c.method}</td>
              <td>{c.account}</td>
              <td className="num">{c.hours}</td>
              <td className="num">{c.hops}</td>
              <td>{c.status}</td>
              <td>{show(c.reason)}</td>
              <td>{c.exact ? "có" : "không"}</td>
              <td className="num">{c.runs}</td>
              <td className="num">{show(c.median_ms)}</td>
              <td className="num">{show(c.p95_ms)}</td>
              <td className="num">{show(c.min_ms)}</td>
              <td className="num">{show(c.max_ms)}</td>
              <td className="num">{show(c.n_paths)}</td>
              <td className="num">{show(c.n_accounts)}</td>
              <td className="num">{show(c.n_cycles)}</td>
              <td className="num">{show(c.query_lines)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunBlock({ run }: { run: BenchRun }) {
  return (
    <article className="bench-block">
      <h3>{run.file}</h3>
      <Meta meta={run.meta} />
      {run.mismatches.length > 0 && (
        <div className="bench-warning" role="alert">
          <strong>Cảnh báo: số đường đi giữa các phương pháp chính xác không khớp.</strong>
          <ul>
            {run.mismatches.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      <CellTable cells={run.cells} />
    </article>
  );
}

export default function BenchmarkPage() {
  return (
    <ApiPanel<BenchData> path="/benchmark" title="Đối chiếu phương pháp truy vết">
      {(data) =>
        data.runs.length === 0 ? (
          <p className="muted">
            Chưa chạy <code>aml bench</code>
          </p>
        ) : (
          <>
            {data.runs.map((run) => (
              <RunBlock key={run.file} run={run} />
            ))}
            <h3>Ghi chú</h3>
            <ul className="bench-notes">
              {data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </>
        )
      }
    </ApiPanel>
  );
}
