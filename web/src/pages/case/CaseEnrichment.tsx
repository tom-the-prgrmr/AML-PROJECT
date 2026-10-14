import type { ReactNode } from "react";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import RuleLabel from "../../components/RuleLabel";
import StatusBadge from "../../components/StatusBadge";
import type { CaseSubject } from "../../api/caseTypes";
import type { CaseDetail } from "../../api/types";
import {
  DASH,
  accountTypeLabel,
  channelLabel,
  dash,
  directionLabel,
  dqDimensionLabel,
  formatDate,
  formatDateTime,
  formatNumber,
  formatVnd,
  kycRiskLabel,
  networkFeatureLabel,
  networkSourceLabel,
  yesNo,
} from "../../i18n";
import "./overview.css";

/** One card of the enrichment grid. */
function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="panel enrich-block">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Pairs({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Identifiers in mono, comma separated; an empty list is an em dash. */
function Codes({ ids }: { ids: string[] }) {
  return ids.length === 0 ? <>{DASH}</> : <span className="code">{ids.join(", ")}</span>;
}

function Kyc({ detail, subjects }: { detail: CaseDetail; subjects: CaseSubject[] }) {
  const kyc = detail.enrichment.kyc;
  const names = new Map(subjects.map((s) => [s.cif, s.full_name]));
  return (
    <Block title="Hồ sơ khách hàng (KYC)">
      <Pairs rows={[["Xếp hạng rủi ro", kycRiskLabel(kyc.risk_rating)]]} />
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
              <td className="code">{c.cif}</td>
              <td>{dash(names.get(c.cif))}</td>
              <td>{kycRiskLabel(c.kyc_risk)}</td>
              <td>{dash(c.occupation)}</td>
              <td>{dash(c.nationality)}</td>
              <td>{dash(c.birth_year)}</td>
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
          ["Số CIF trong cụm", formatNumber(linked.cluster_size)],
          ["Các CIF", <Codes ids={linked.cifs} />],
          ["Số cặp hồ sơ khớp", formatNumber(linked.er?.pairs)],
          ["Trọng số khớp thấp nhất", formatNumber(linked.er?.min_match_weight)],
        ]}
      />
      <table className="data">
        <thead>
          <tr>
            <th>Tài khoản</th>
            <th>CIF</th>
            <th>Loại tài khoản</th>
            <th>Ngày mở</th>
          </tr>
        </thead>
        <tbody>
          {linked.accounts.map((a) => (
            <tr key={a.account_id}>
              <td className="code">{a.account_id}</td>
              <td className="code">{a.cif}</td>
              <td>{accountTypeLabel(a.account_type)}</td>
              <td>{formatDate(a.open_date)}</td>
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
      {dq.customer.length === 0 && txnRules.length === 0 && (
        <EmptyState title="Không có vấn đề chất lượng dữ liệu" />
      )}
      {dq.customer.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>CIF</th>
              <th>Luật kiểm tra hồ sơ</th>
              <th>Tiêu chí</th>
            </tr>
          </thead>
          <tbody>
            {dq.customer.map((i) => (
              <tr key={`${i.cif}-${i.rule_id}`}>
                <td className="code">{i.cif}</td>
                <td>
                  <RuleLabel id={i.rule_id} />
                </td>
                <td>{dqDimensionLabel(i.dimension)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {txnRules.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Luật kiểm tra giao dịch</th>
              <th className="num">Số giao dịch vi phạm</th>
            </tr>
          </thead>
          <tbody>
            {txnRules.map(([rule, count]) => (
              <tr key={rule}>
                <td>
                  <RuleLabel id={rule} />
                </td>
                <td className="num">{formatNumber(count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Block>
  );
}

function TxnSummary({ detail }: { detail: CaseDetail }) {
  const t = detail.enrichment.txn_summary;
  const channels = Object.entries(t.by_channel);
  return (
    <Block title="Tóm tắt giao dịch">
      <Pairs
        rows={[
          ["Từ", formatDateTime(t.window_start)],
          ["Đến", formatDateTime(t.window_end)],
          ["Số giao dịch", formatNumber(t.txn_count)],
          ["Số giao dịch vào", formatNumber(t.in_count)],
          ["Tiền vào (VND)", formatVnd(t.in_vnd)],
          ["Số giao dịch ra", formatNumber(t.out_count)],
          ["Tiền ra (VND)", formatVnd(t.out_vnd)],
          ["Tiền mặt vào (VND)", formatVnd(t.cash_in_vnd)],
          ["Tiền mặt ra (VND)", formatVnd(t.cash_out_vnd)],
          ["Số đối tác", formatNumber(t.counterparties)],
          ["Giao dịch lớn nhất (VND)", formatVnd(t.max_txn_vnd)],
          ["Số ngày có giao dịch", formatNumber(t.active_days)],
        ]}
      />
      {channels.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Kênh</th>
              <th className="num">Số giao dịch</th>
              <th className="num">Số tiền (VND)</th>
            </tr>
          </thead>
          <tbody>
            {channels.map(([channel, v]) => (
              <tr key={channel}>
                <td>{channelLabel(channel)}</td>
                <td className="num">{formatNumber(v.count)}</td>
                <td className="num">{formatVnd(v.vnd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Block>
  );
}

/** A network feature by its key: a flag as Có / Không, an id in mono, a number with grouping. */
function featureValue(key: string, value: number | string | null): ReactNode {
  if (value === null) return DASH;
  if (key === "is_hub") return yesNo(Number(value) !== 0);
  if (typeof value === "string") return <span className="code">{value}</span>;
  return formatNumber(value);
}

function Network({ detail }: { detail: CaseDetail }) {
  const net = detail.enrichment.network;
  const features: [string, ReactNode][] = Object.entries(net.features).map(([key, value]) => [
    networkFeatureLabel(key),
    featureValue(key, value),
  ]);
  return (
    <Block title="Mạng lưới">
      <Pairs
        rows={[
          ["Nguồn chỉ số mạng", networkSourceLabel(net.source)],
          ...features,
          ["Case có chung cảnh báo", <Codes ids={net.shared_alert_cases} />],
        ]}
      />
      {net.counterparties.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Tài khoản đối tác</th>
              <th>Khách hàng gộp</th>
              <th>Chiều tiền</th>
              <th className="num">Số giao dịch</th>
              <th className="num">Số tiền (VND)</th>
            </tr>
          </thead>
          <tbody>
            {net.counterparties.map((c) => (
              <tr key={`${c.account_id}-${c.direction}`}>
                <td className="code">{c.account_id}</td>
                <td className="code">{dash(c.golden_customer_id)}</td>
                <td>{directionLabel(c.direction)}</td>
                <td className="num">{formatNumber(c.txns)}</td>
                <td className="num">{formatVnd(c.vnd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Block>
  );
}

function History({ detail }: { detail: CaseDetail }) {
  const h = detail.enrichment.history;
  return (
    <Block title="Lịch sử">
      <Pairs
        rows={[
          ["Số cảnh báo trước đó", formatNumber(h.prior_alerts)],
          ["Kết quả sàng lọc tự động loại", formatNumber(h.screening_auto_cleared)],
          ["Cảnh báo đã bị chặn", formatNumber(h.suppressed_items)],
        ]}
      />
      {h.prior_cases.length === 0 ? (
        <EmptyState title="Không có case trước đó" />
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>Mã case</th>
              <th>Cảnh báo đầu tiên</th>
              <th className="num">Số cảnh báo</th>
              <th>Quyết định</th>
              <th>Ngày quyết định</th>
            </tr>
          </thead>
          <tbody>
            {h.prior_cases.map((c) => (
              <tr key={c.case_id}>
                <td className="code">{c.case_id}</td>
                <td>{formatDateTime(c.first_alert_ts)}</td>
                <td className="num">{formatNumber(c.alerts)}</td>
                <td>
                  <StatusBadge kind="disposition" value={c.disposition} />
                </td>
                <td>{formatDate(c.decided_on)}</td>
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
