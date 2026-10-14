import { useState } from "react";
import ApiPanel from "../../components/ApiPanel";
import Pager from "../../components/Pager";
import type { CaseTransaction } from "../../api/caseTypes";
import type { CaseDetail } from "../../api/types";
import "./overview.css";

function text(value: string | null): string {
  return value === null ? "—" : value;
}

export default function CaseEvidence({ detail }: { detail: CaseDetail }) {
  const [offset, setOffset] = useState(0);
  const txnPath = `/cases/${encodeURIComponent(detail.case_id)}/transactions?offset=${offset}`;
  return (
    <section className="panel">
      <h2>Alert và giao dịch bằng chứng</h2>
      <h3>Alert</h3>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Nguồn</th>
              <th>Rule</th>
              <th>Mã alert</th>
              <th>CIF</th>
              <th>Bắt đầu</th>
              <th>Kết thúc</th>
              <th className="num">Số tiền (VND)</th>
              <th>Lý do</th>
            </tr>
          </thead>
          <tbody>
            {detail.alerts.map((a) => (
              <tr key={a.item_key}>
                <td>{a.source}</td>
                <td>{a.rule_id}</td>
                <td>{a.alert_ref}</td>
                <td>{a.cif}</td>
                <td>{a.event_ts}</td>
                <td>{a.end_ts}</td>
                <td className="num">{a.amount_vnd}</td>
                <td>{a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Giao dịch</h3>
      <ApiPanel<CaseTransaction[]> path={txnPath}>
        {(rows, meta) => (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Mã GD</th>
                  <th>Thời gian</th>
                  <th>Từ TK</th>
                  <th>Đến TK</th>
                  <th className="num">Số tiền (VND)</th>
                  <th>Kênh</th>
                  <th>Nội dung</th>
                  <th>Tên đối tác</th>
                  <th>Alert</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.txn_id}>
                    <td>{t.txn_id}</td>
                    <td>{t.txn_ts}</td>
                    <td>{text(t.from_account_id)}</td>
                    <td>{text(t.to_account_id)}</td>
                    <td className="num">{t.amount_vnd}</td>
                    <td>{text(t.channel)}</td>
                    <td className="memo-cell">{text(t.memo)}</td>
                    <td>{text(t.counterparty_name)}</td>
                    <td>{t.item_keys.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager
              offset={Number(meta.offset ?? 0)}
              limit={Number(meta.limit ?? rows.length)}
              total={Number(meta.total ?? rows.length)}
              shown={rows.length}
              onPage={setOffset}
            />
          </div>
        )}
      </ApiPanel>
    </section>
  );
}
