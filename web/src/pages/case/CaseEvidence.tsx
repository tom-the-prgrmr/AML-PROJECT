import { useState } from "react";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import Pager from "../../components/Pager";
import RuleLabel from "../../components/RuleLabel";
import StatusBadge from "../../components/StatusBadge";
import type { CaseTransaction } from "../../api/caseTypes";
import type { CaseAlert, CaseDetail } from "../../api/types";
import { DASH, channelLabel, dash, formatDateTime, formatVnd, ruleName } from "../../i18n";
import "./overview.css";

/** An item key is "<rule id>|<subject>|<time>": the rule in words, the rest as the identifier it is. */
function ItemKey({ itemKey }: { itemKey: string }) {
  const [rule, ...rest] = itemKey.split("|");
  return (
    <div className="item-key">
      {ruleName(rule)}
      {rest.length > 0 && <code className="cell-sub">{rest.join(" · ")}</code>}
    </div>
  );
}

function AlertTable({ alerts }: { alerts: CaseAlert[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Nguồn</th>
            <th>Luật</th>
            <th>Mã cảnh báo</th>
            <th>CIF</th>
            <th>Bắt đầu</th>
            <th>Kết thúc</th>
            <th className="num">Số tiền (VND)</th>
            <th>Lý do</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.item_key}>
              <td>
                <StatusBadge kind="source" value={a.source} />
              </td>
              <td>
                <RuleLabel id={a.rule_id} />
              </td>
              <td className="code">{a.alert_ref}</td>
              <td className="code">{a.cif}</td>
              <td className="nowrap">{formatDateTime(a.event_ts)}</td>
              <td className="nowrap">{formatDateTime(a.end_ts)}</td>
              <td className="num">{formatVnd(a.amount_vnd)}</td>
              <td className="reason-cell">{a.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionTable({ rows }: { rows: CaseTransaction[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Mã giao dịch</th>
            <th>Thời gian</th>
            <th>Tài khoản gửi</th>
            <th>Tài khoản nhận</th>
            <th className="num">Số tiền (VND)</th>
            <th>Kênh</th>
            <th>Nội dung</th>
            <th>Tên đối tác</th>
            <th>Cảnh báo liên quan</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.txn_id}>
              <td className="code">{t.txn_id}</td>
              <td className="nowrap">{formatDateTime(t.txn_ts)}</td>
              <td className="code">{dash(t.from_account_id)}</td>
              <td className="code">{dash(t.to_account_id)}</td>
              <td className="num">{formatVnd(t.amount_vnd)}</td>
              <td>{channelLabel(t.channel)}</td>
              <td className="memo-cell">{dash(t.memo)}</td>
              <td>{dash(t.counterparty_name)}</td>
              <td>
                {t.item_keys.length === 0
                  ? DASH
                  : t.item_keys.map((key) => <ItemKey key={key} itemKey={key} />)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CaseEvidence({ detail }: { detail: CaseDetail }) {
  const [offset, setOffset] = useState(0);
  const txnPath = `/cases/${encodeURIComponent(detail.case_id)}/transactions?offset=${offset}`;
  return (
    <>
      <section className="panel">
        <h2>Cảnh báo của case</h2>
        {detail.alerts.length === 0 ? (
          <EmptyState title="Case không có cảnh báo nào" />
        ) : (
          <AlertTable alerts={detail.alerts} />
        )}
      </section>
      <ApiPanel<CaseTransaction[]> path={txnPath} title="Giao dịch bằng chứng">
        {(rows, meta) => (
          <>
            {rows.length === 0 ? (
              <EmptyState
                title="Không có giao dịch bằng chứng"
                hint="Các cảnh báo của case này không gắn với giao dịch nào."
              />
            ) : (
              <TransactionTable rows={rows} />
            )}
            <Pager
              offset={Number(meta.offset ?? 0)}
              limit={Number(meta.limit ?? rows.length)}
              total={Number(meta.total ?? rows.length)}
              shown={rows.length}
              onPage={setOffset}
            />
          </>
        )}
      </ApiPanel>
    </>
  );
}
