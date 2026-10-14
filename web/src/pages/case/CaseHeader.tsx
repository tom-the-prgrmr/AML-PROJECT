import type { CaseDetail } from "../../api/types";
import "./overview.css";

export default function CaseHeader({ detail }: { detail: CaseDetail }) {
  const decision = detail.disposition;
  return (
    <section className="panel case-header">
      <h2>Case {detail.case_id}</h2>
      <dl>
        <dt>Khách hàng gộp</dt>
        <dd>{detail.golden_customer_id}</dd>
        <dt>Trạng thái</dt>
        <dd>
          <span className="badge">{detail.status}</span>
        </dd>
        <dt>Quyết định</dt>
        <dd>
          {decision === null ? (
            <span className="muted">Chưa có quyết định</span>
          ) : (
            <span className="badge">{decision.disposition}</span>
          )}
        </dd>
        {decision !== null && (
          <>
            <dt>Người quyết định</dt>
            <dd>
              {decision.actor} ({decision.origin}), ngày {decision.decided_on}
            </dd>
            <dt>Lý do quyết định</dt>
            <dd>{decision.reason}</dd>
          </>
        )}
        <dt>Cửa sổ</dt>
        <dd>
          {detail.window_start} đến {detail.last_alert_ts}
        </dd>
        <dt>Alert đầu tiên</dt>
        <dd>{detail.first_alert_ts}</dd>
        <dt>Lý do gộp case</dt>
        <dd>{detail.reason}</dd>
      </dl>
      <p className="muted">
        Trạng thái chỉ đổi ở lần chạy <code>aml cases build</code> kế tiếp; ghi quyết định không đổi
        trạng thái ngay.
      </p>
    </section>
  );
}
