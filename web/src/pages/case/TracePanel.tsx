import { Fragment, useState, type FormEvent } from "react";
import type { LinkedAccount } from "../../api/types";
import type {
  TraceMeta,
  TraceMethodInfo,
  TraceMethodsMeta,
  TracePath,
  TraceQuery,
} from "../../api/traceTypes";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import Pager from "../../components/Pager";
import {
  accountTypeLabel,
  backendLabel,
  formatDateTime,
  formatNumber,
  formatVnd,
  traceMethodLabel,
  skipReason,
} from "../../i18n";
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

/** Ids joined by plain-text arrows, each id in mono: "A → B → C". */
function IdChain({ ids }: { ids: string[] }) {
  return (
    <span className="trace-chain">
      {ids.map((id, i) => (
        <Fragment key={`${i}-${id}`}>
          {i > 0 && <span className="trace-arrow"> → </span>}
          <span className="code">{id}</span>
        </Fragment>
      ))}
    </span>
  );
}

function MethodCard(props: { info: TraceMethodInfo; checked: boolean; onPick: () => void }) {
  const { info, checked, onPick } = props;
  const cls = ["trace-method", checked && "checked", !info.available && "disabled"].filter(Boolean).join(" ");
  return (
    <label className={cls}>
      <input
        type="radio"
        name="trace-method"
        value={info.method}
        checked={checked}
        disabled={!info.available}
        onChange={onPick}
      />
      <span className="trace-method-body">
        <span className="trace-method-name">
          {traceMethodLabel(info.method)}
          {!info.exact && <span className="badge badge-warn">xấp xỉ</span>}
        </span>
        {!info.available && info.reason && <span className="trace-reason">{skipReason(info.reason)}</span>}
      </span>
    </label>
  );
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
    <form className="trace-form" onSubmit={submit}>
      <div className="trace-fields">
        <label className="trace-field trace-field-wide">
          Tài khoản xuất phát
          <select value={account} onChange={(e) => setAccount(e.target.value)}>
            {accounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.account_id}
                {a.account_type ? ` - ${accountTypeLabel(a.account_type)}` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="trace-field">
          Số bước
          <input
            type="number"
            min={1}
            max={limits.max_hops}
            value={hops}
            onChange={(e) => setHops(Number(e.target.value))}
          />
          <span className="trace-help">Từ 1 đến {formatNumber(limits.max_hops)}</span>
        </label>
        <label className="trace-field">
          Số giờ
          <input
            type="number"
            min={1}
            max={limits.max_hours}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          />
          <span className="trace-help">Từ 1 đến {formatNumber(limits.max_hours)}</span>
        </label>
      </div>
      <fieldset className="trace-methods">
        <legend>Phương pháp truy vết</legend>
        <div className="trace-method-grid">
          {methods.map((m) => (
            <MethodCard
              key={m.method}
              info={m}
              checked={method === m.method}
              onPick={() => setMethod(m.method)}
            />
          ))}
        </div>
      </fieldset>
      <div className="trace-actions">
        <button type="submit" className="btn-primary" disabled={!account}>
          Truy vết
        </button>
        <span className="muted trace-help">
          Mỗi lần truy vết (và mỗi lần chuyển trang kết quả) đều được ghi vào nhật ký kiểm toán.
        </span>
      </div>
    </form>
  );
}

function Summary({ meta }: { meta: TraceMeta }) {
  return (
    <p className="trace-summary">
      <strong>{formatNumber(meta.n_paths)}</strong> đường đi tới <strong>{formatNumber(meta.n_accounts)}</strong>{" "}
      tài khoản, <strong>{formatNumber(meta.n_cycles)}</strong> đường khép vòng;{" "}
      {formatNumber(meta.seconds)} giây, {formatNumber(meta.query_lines)} dòng truy vấn. Phương pháp:{" "}
      {traceMethodLabel(meta.method)} trên {backendLabel(meta.backend)}.
      {!meta.exact && <span className="badge badge-warn">xấp xỉ</span>}
    </p>
  );
}

function Results(props: { rows: TracePath[]; meta: TraceMeta; onPage: (offset: number) => void }) {
  const { rows, meta, onPage } = props;
  const { highlightIds, setHighlight } = useCaseHighlight();
  const [picked, setPicked] = useState<string | null>(null);
  const shown = highlightIds.join(">");
  return (
    <>
      <Summary meta={meta} />
      {rows.length === 0 ? (
        <EmptyState title="Không có đường đi nào." hint="Thử tăng số bước hoặc số giờ." />
      ) : (
        <>
          <p className="muted trace-help">Bấm vào một dòng để tô sáng đường đi trên đồ thị mạng lưới.</p>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th className="num">Số bước</th>
                  <th>Đường đi qua các tài khoản</th>
                  <th>Chuỗi giao dịch</th>
                  <th>Giao dịch đầu</th>
                  <th>Giao dịch cuối</th>
                  <th className="num">Số tiền (VND)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const key = `${p.path}|${p.step_path}`;
                  const selected = key === picked && shown === p.path;
                  return (
                    <tr
                      key={key}
                      className={selected ? "clickable selected" : "clickable"}
                      onClick={() => {
                        setPicked(key);
                        setHighlight(p.path.split(">"));
                      }}
                    >
                      <td className="num">{formatNumber(p.hop)}</td>
                      <td className="wrap">
                        <IdChain ids={p.path.split(">")} />
                        {p.is_cycle && <span className="badge badge-bad trace-cycle">Khép vòng</span>}
                      </td>
                      <td className="wrap">
                        <IdChain ids={p.step_path.split(">")} />
                      </td>
                      <td>{formatDateTime(p.first_ts)}</td>
                      <td>{formatDateTime(p.last_ts)}</td>
                      <td className="num">{formatVnd(p.amount_vnd)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      <Pager offset={meta.offset} limit={meta.limit} total={meta.total} shown={rows.length} onPage={onPage} />
    </>
  );
}

export default function TracePanel({ accounts }: { accounts: LinkedAccount[] }) {
  const [query, setQuery] = useState<TraceQuery | null>(null);

  if (accounts.length === 0) {
    return (
      <section className="panel">
        <h2>Truy vết dòng tiền</h2>
        <EmptyState title="Hồ sơ này không có tài khoản liên kết để truy vết." />
      </section>
    );
  }

  return (
    <section className="panel" aria-label="Truy vết dòng tiền">
      <ApiPanel<TraceMethodInfo[]> path="/trace/methods" title="Truy vết dòng tiền">
        {(methods, meta) => (
          <TraceForm
            accounts={accounts}
            methods={methods}
            limits={meta as unknown as TraceMethodsMeta}
            onRun={setQuery}
          />
        )}
      </ApiPanel>
      {query && (
        <ApiPanel<TracePath[]> path={tracePath(query)} title="Kết quả truy vết">
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
