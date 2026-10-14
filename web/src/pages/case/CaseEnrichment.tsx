import type { ReactNode } from "react";
import ApiPanel from "../../components/ApiPanel";
import type { CaseSubject } from "../../api/caseTypes";
import type { CaseDetail } from "../../api/types";
import "./overview.css";

type Cell = string | number | null | undefined;

/** A missing value is an em dash, never 0 or an empty cell. */
function show(value: Cell): string {
  return value === null || value === undefined ? "—" : String(value);
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="enrich-block">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Pairs({ rows }: { rows: [string, Cell][] }) {
  return (
    <dl>
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Kyc({ detail, subjects }: { detail: CaseDetail; subjects: CaseSubject[] }) {
  const kyc = detail.enrichment.kyc;
  const names = new Map(subjects.map((s) => [s.cif, s.full_name]));
  return (
    <Block title="KYC">
      <Pairs rows={[["Xếp hạng rủi ro", kyc.risk_rating]]} />
      <table className="data">
        <thead>
          <tr>
            <th>CIF</th>
            <th>Họ tên</th>
            <th>Rủi ro KYC</th>
            <th>Nghề nghiệp</th>
            <th>Quốc tịch</th>
            <th>Năm sinh</th>
          </tr>
        </thead>
        <tbody>
          {kyc.cifs.map((c) => (
            <tr key={c.cif}>
              <td>{c.cif}</td>
              <td>{show(names.get(c.cif))}</td>
              <td>{show(c.kyc_risk)}</td>
              <td>{show(c.occupation)}</td>
              <td>{show(c.nationality)}</td>
              <td>{show(c.birth_year)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Block>
  );
}

function Linked({ detail }: { detail: CaseDetail }) {
  const linked = detail.enrichment.linked_cifs;
  return (
    <Block title="CIF liên kết">
      <Pairs
        rows={[
          ["Số CIF trong cụm", linked.cluster_size],
          ["CIF", linked.cifs.join(", ")],
          ["Cặp ER", linked.er?.pairs],
          ["Trọng số khớp tối thiểu", linked.er?.min_match_weight],
        ]}
      />
      <table className="data">
        <thead>
          <tr>
            <th>Tài khoản</th>
            <th>CIF</th>
            <th>Loại</th>
            <th>Ngày mở</th>
          </tr>
        </thead>
        <tbody>
          {linked.accounts.map((a) => (
            <tr key={a.account_id}>
              <td>{a.account_id}</td>
              <td>{a.cif}</td>
              <td>{show(a.account_type)}</td>
              <td>{show(a.open_date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Block>
  );
}

function Dq({ detail }: { detail: CaseDetail }) {
  const dq = detail.enrichment.dq_issues;
  const txnRules = Object.entries(dq.transactions);
  return (
    <Block title="Vấn đề chất lượng dữ liệu">
      {dq.customer.length === 0 && txnRules.length === 0 && <p className="muted">Không có</p>}
      {dq.customer.length > 0 && (
        <ul>
          {dq.customer.map((i) => (
            <li key={`${i.cif}-${i.rule_id}`}>
              {i.cif}: {i.rule_id} ({show(i.dimension)})
            </li>
          ))}
        </ul>
      )}
      {txnRules.length > 0 && (
        <ul>
          {txnRules.map(([rule, count]) => (
            <li key={rule}>
              Giao dịch {rule}: {count}
            </li>
          ))}
        </ul>
      )}
    </Block>
  );
}

function TxnSummary({ detail }: { detail: CaseDetail }) {
  const t = detail.enrichment.txn_summary;
  return (
    <Block title="Tóm tắt giao dịch">
      <Pairs
        rows={[
          ["Từ ngày", t.window_start],
          ["Đến ngày", t.window_end],
          ["Số giao dịch", t.txn_count],
          ["Số GD vào", t.in_count],
          ["Tiền vào (VND)", t.in_vnd],
          ["Số GD ra", t.out_count],
          ["Tiền ra (VND)", t.out_vnd],
          ["Tiền mặt vào (VND)", t.cash_in_vnd],
          ["Tiền mặt ra (VND)", t.cash_out_vnd],
          ["Đối tác", t.counterparties],
          ["GD lớn nhất (VND)", t.max_txn_vnd],
          ["Số ngày hoạt động", t.active_days],
        ]}
      />
      <ul>
        {Object.entries(t.by_channel).map(([channel, v]) => (
          <li key={channel}>
            {channel}: {v.count} GD, {v.vnd} VND
          </li>
        ))}
      </ul>
    </Block>
  );
}

function Network({ detail }: { detail: CaseDetail }) {
  const net = detail.enrichment.network;
  const features: [string, Cell][] = Object.entries(net.features);
  return (
    <Block title="Mạng lưới">
      <Pairs
        rows={[
          ["Nguồn", net.source],
          ...features,
          ["Case chung alert", net.shared_alert_cases.join(", ") || null],
        ]}
      />
      <table className="data">
        <thead>
          <tr>
            <th>Tài khoản đối tác</th>
            <th>Khách hàng gộp</th>
            <th>Chiều</th>
            <th className="num">Số GD</th>
            <th className="num">VND</th>
          </tr>
        </thead>
        <tbody>
          {net.counterparties.map((c) => (
            <tr key={`${c.account_id}-${c.direction}`}>
              <td>{c.account_id}</td>
              <td>{show(c.golden_customer_id)}</td>
              <td>{c.direction}</td>
              <td className="num">{c.txns}</td>
              <td className="num">{c.vnd}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Block>
  );
}

function History({ detail }: { detail: CaseDetail }) {
  const h = detail.enrichment.history;
  return (
    <Block title="Lịch sử">
      <Pairs
        rows={[
          ["Alert trước đó", h.prior_alerts],
          ["Screening tự xoá", h.screening_auto_cleared],
          ["Mục bị chặn", h.suppressed_items],
        ]}
      />
      {h.prior_cases.length === 0 ? (
        <p className="muted">Không có case trước</p>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Case</th>
              <th>Alert đầu</th>
              <th className="num">Alert</th>
              <th>Quyết định</th>
              <th>Ngày</th>
            </tr>
          </thead>
          <tbody>
            {h.prior_cases.map((c) => (
              <tr key={c.case_id}>
                <td>{c.case_id}</td>
                <td>{show(c.first_alert_ts)}</td>
                <td className="num">{c.alerts}</td>
                <td>{show(c.disposition)}</td>
                <td>{show(c.decided_on)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Block>
  );
}

export default function CaseEnrichment({ detail }: { detail: CaseDetail }) {
  return (
    <section className="panel">
      <h2>Thông tin bổ sung</h2>
      <ApiPanel<CaseSubject[]> path={`/cases/${encodeURIComponent(detail.case_id)}/subjects`}>
        {(subjects) => (
          <div className="enrich-grid">
            <Kyc detail={detail} subjects={subjects} />
            <Linked detail={detail} />
            <Dq detail={detail} />
            <TxnSummary detail={detail} />
            <Network detail={detail} />
            <History detail={detail} />
          </div>
        )}
      </ApiPanel>
    </section>
  );
}
