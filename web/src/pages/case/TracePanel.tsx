import { useState, type FormEvent } from "react";
import type { LinkedAccount } from "../../api/types";
import type {
  TraceMeta,
  TraceMethodInfo,
  TraceMethodsMeta,
  TracePath,
  TraceQuery,
} from "../../api/traceTypes";
import ApiPanel from "../../components/ApiPanel";
import { useCaseHighlight } from "../caseHighlight";
import "./trace.css";

const PAGE = 50;

function tracePath(q: TraceQuery): string {
  const params = new URLSearchParams({
    method: q.method,
    hops: String(q.hops),
    hours: String(q.hours),
    limit: String(PAGE),
    offset: String(q.offset),
  });
  return `/accounts/${encodeURIComponent(q.account)}/trace?${params.toString()}`;
}

function TraceForm(props: {
  accounts: LinkedAccount[];
  methods: TraceMethodInfo[];
  limits: TraceMethodsMeta;
  onRun: (q: TraceQuery) => void;
}) {
  const { accounts, methods, limits, onRun } = props;
  const [account, setAccount] = useState(accounts[0]?.account_id ?? "");
  const [hops, setHops] = useState(limits.default_hops);
  const [hours, setHours] = useState(limits.default_hours);
  const [method, setMethod] = useState(limits.default_method);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (account) onRun({ account, method, hops, hours, offset: 0 });
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Tài khoản xuất phát
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          {accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.account_id}
            </option>
          ))}
        </select>
      </label>
      <label>
        Số bước (1-{limits.max_hops})
        <input
          type="number"
          min={1}
          max={limits.max_hops}
          value={hops}
          onChange={(e) => setHops(Number(e.target.value))}
        />
      </label>
      <label>
        Số giờ (1-{limits.max_hours})
        <input
          type="number"
          min={1}
          max={limits.max_hours}
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
        />
      </label>
      <fieldset>
        <legend>Phương pháp</legend>
        {methods.map((m) => (
          <div key={m.method} className={m.available ? "trace-method" : "trace-method disabled"}>
            <label>
              <input
                type="radio"
                name="trace-method"
                value={m.method}
                checked={method === m.method}
                disabled={!m.available}
                onChange={() => setMethod(m.method)}
              />{" "}
              {m.label}
            </label>
            {!m.available && m.reason && <div className="muted trace-reason">{m.reason}</div>}
          </div>
        ))}
      </fieldset>
      <button type="submit" disabled={!account}>
        Truy vết
      </button>
    </form>
  );
}

function Summary({ meta }: { meta: TraceMeta }) {
  return (
    <p className="trace-summary">
      {meta.n_paths} đường đi tới {meta.n_accounts} tài khoản, {meta.n_cycles} bước khép vòng;{" "}
      {meta.seconds.toFixed(3)} giây, {meta.query_lines} dòng truy vấn ({meta.method} trên{" "}
      {meta.backend}).
      {!meta.exact && <span className="badge"> xấp xỉ</span>}
    </p>
  );
}

function Results(props: { rows: TracePath[]; meta: TraceMeta; onPage: (offset: number) => void }) {
  const { rows, meta, onPage } = props;
  const { setHighlight } = useCaseHighlight();
  const end = meta.offset + rows.length;
  return (
    <>
      <Summary meta={meta} />
      {rows.length === 0 ? (
        <p className="muted">Không có đường đi nào.</p>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Bước</th>
              <th>Đường đi</th>
              <th>Giao dịch</th>
              <th>Đầu</th>
              <th>Cuối</th>
              <th>Số tiền (VND)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr
                key={`${p.path}|${p.step_path}`}
                className={p.is_cycle ? "trace-row cycle" : "trace-row"}
                onClick={() => setHighlight(p.path.split(">"))}
              >
                <td>{p.hop}</td>
                <td>
                  {p.path}
                  {p.is_cycle && " (vòng)"}
                </td>
                <td>{p.step_path}</td>
                <td>{p.first_ts}</td>
                <td>{p.last_ts}</td>
                <td>{p.amount_vnd.toLocaleString("vi-VN")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="toolbar">
        <button type="button" disabled={meta.offset === 0} onClick={() => onPage(meta.offset - meta.limit)}>
          Trước
        </button>
        <span>
          {meta.total === 0 ? 0 : meta.offset + 1}-{end} / {meta.total}
        </span>
        <button type="button" disabled={end >= meta.total} onClick={() => onPage(meta.offset + meta.limit)}>
          Sau
        </button>
      </div>
    </>
  );
}

export default function TracePanel({ accounts }: { accounts: LinkedAccount[] }) {
  const [query, setQuery] = useState<TraceQuery | null>(null);

  return (
    <section className="panel">
      <h2>Truy vết dòng tiền</h2>
      {accounts.length === 0 ? (
        <p className="muted">Hồ sơ này không có tài khoản liên kết để truy vết.</p>
      ) : (
        <ApiPanel<TraceMethodInfo[]> path="/trace/methods">
          {(methods, meta) => (
            <TraceForm
              accounts={accounts}
              methods={methods}
              limits={meta as unknown as TraceMethodsMeta}
              onRun={setQuery}
            />
          )}
        </ApiPanel>
      )}
      {query && (
        <ApiPanel<TracePath[]> path={tracePath(query)}>
          {(rows, meta) => (
            <Results
              rows={rows}
              meta={meta as unknown as TraceMeta}
              onPage={(offset) => setQuery({ ...query, offset: Math.max(0, offset) })}
            />
          )}
        </ApiPanel>
      )}
    </section>
  );
}
