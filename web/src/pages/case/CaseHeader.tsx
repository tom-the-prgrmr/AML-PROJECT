import { Link } from "react-router-dom";
import type { CaseDetail, Disposition } from "../../api/types";
import PageHeader from "../../components/PageHeader";
import Stat from "../../components/Stat";
import StatusBadge from "../../components/StatusBadge";
import {
  actorLabel,
  dispositionOriginLabel,
  formatDate,
  formatDateTime,
  formatNumber,
} from "../../i18n";
import "./overview.css";

/** The recorded decision: who, when and why. It is separate from the status of the case. */
function Decision({ decision }: { decision: Disposition | null }) {
  if (decision === null) {
    return <p className="muted">Chưa có quyết định nào được ghi cho case này.</p>;
  }
  return (
    <dl className="kv">
      <div>
        <dt>Kết luận</dt>
        <dd>
          <StatusBadge kind="disposition" value={decision.disposition} />
        </dd>
      </div>
      <div>
        <dt>Người quyết định</dt>
        <dd>{actorLabel(decision.actor)}</dd>
      </div>
      <div>
        <dt>Hình thức</dt>
        <dd>{dispositionOriginLabel(decision.origin)}</dd>
      </div>
      <div>
        <dt>Ngày quyết định</dt>
        <dd>{formatDate(decision.decided_on)}</dd>
      </div>
      <div>
        <dt>Lý do quyết định</dt>
        <dd className="free-text">{decision.reason}</dd>
      </div>
    </dl>
  );
}

export default function CaseHeader({ detail }: { detail: CaseDetail }) {
  const decision = detail.disposition;
  return (
    <>
      <PageHeader
        title={`Case ${detail.case_id}`}
        subtitle={
          <>
            Khách hàng gộp <span className="code">{detail.golden_customer_id}</span>
          </>
        }
        actions={
          <Link className="btn btn-ghost" to="/cases">
            Về hàng đợi case
          </Link>
        }
      />
      <div className="stat-row">
        <Stat
          label="Trạng thái"
          value={<StatusBadge kind="caseStatus" value={detail.status} />}
          tone="info"
        />
        <Stat
          label="Quyết định"
          value={
            decision === null ? (
              <span className="badge badge-neutral">Chưa có quyết định</span>
            ) : (
              <StatusBadge kind="disposition" value={decision.disposition} />
            )
          }
        />
        <Stat label="Số cảnh báo" value={formatNumber(detail.alerts.length)} />
        <Stat
          label="Số CIF trong cụm"
          value={formatNumber(detail.enrichment.linked_cifs.cluster_size)}
        />
        <Stat label="Số giao dịch" value={formatNumber(detail.enrichment.txn_summary.txn_count)} />
      </div>
      <div className="case-header">
        <section className="panel">
          <h2>Thông tin case</h2>
          <dl className="kv">
            <div>
              <dt>Lượt chạy</dt>
              <dd>{detail.run_id}</dd>
            </div>
            <div>
              <dt>Cửa sổ xét</dt>
              <dd>
                {formatDateTime(detail.window_start)} đến {formatDateTime(detail.last_alert_ts)}
              </dd>
            </div>
            <div>
              <dt>Cảnh báo đầu tiên</dt>
              <dd>{formatDateTime(detail.first_alert_ts)}</dd>
            </div>
            <div>
              <dt>Cảnh báo gần nhất</dt>
              <dd>{formatDateTime(detail.last_alert_ts)}</dd>
            </div>
            <div>
              <dt>Lý do gộp case</dt>
              <dd>{detail.reason}</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Quyết định đã ghi</h2>
          <Decision decision={decision} />
          <p className="muted case-note">
            Trạng thái chỉ đổi ở lần chạy <code>aml cases build</code> kế tiếp; ghi quyết định không
            đổi trạng thái ngay.
          </p>
        </section>
      </div>
    </>
  );
}
