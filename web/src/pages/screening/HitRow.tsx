import { Link } from "react-router-dom";
import type { Hit, HitCustomer } from "../../api/screeningTypes";
import StatusBadge from "../../components/StatusBadge";
import {
  DASH,
  actorLabel,
  dash,
  formatDate,
  formatNumber,
  genderLabel,
  idTypeLabel,
  listTypeLabel,
  nameTypeLabel,
} from "../../i18n";
import ReviewForm from "./ReviewForm";

interface Props {
  hit: Hit;
  onRecorded: () => void;
}

/**
 * One score of a hit: Vietnamese label, the value as the API returned it, and the field name
 * with what it measures as a tooltip, so it can be traced to src/aml/screening/scoring.py.
 */
function Score(props: { label: string; field: string; meaning: string; value: string }) {
  return (
    <div>
      <dt title={`${props.field}: ${props.meaning}`}>{props.label}</dt>
      <dd>{props.value}</dd>
    </div>
  );
}

function Customer({ cif, customer }: { cif: string; customer: HitCustomer | null }) {
  const cifLine = (
    <span className="cell-sub">
      CIF <span className="code">{cif}</span>
    </span>
  );
  if (!customer) {
    return (
      <>
        <span className="screening-name muted">Không còn hồ sơ khách hàng</span>
        {cifLine}
      </>
    );
  }
  return (
    <>
      {/* full_name arrives already masked for analysts; it is shown exactly as returned. */}
      <span className="screening-name">{dash(customer.full_name)}</span>
      {cifLine}
      <span className="cell-sub">
        Năm sinh {dash(customer.birth_year)} · Quốc tịch {dash(customer.nationality)} · Giới tính{" "}
        {genderLabel(customer.gender)}
      </span>
      <span className="cell-sub">
        {idTypeLabel(customer.id_type)} <span className="code">{dash(customer.id_number)}</span>
      </span>
    </>
  );
}

export default function HitRow({ hit, onRecorded }: Props) {
  const review = hit.review;
  return (
    <tr>
      <td className="screening-party">
        <Customer cif={hit.cif} customer={hit.customer} />
      </td>
      <td className="screening-party">
        <span className="screening-name">{hit.matched_name}</span>
        <span className="cell-sub">
          Mã mục <span className="code">{hit.entry_id}</span>
        </span>
        <span className="screening-tags">
          <span className="badge badge-neutral">{listTypeLabel(hit.list_type)}</span>
          <span className="badge badge-neutral">{nameTypeLabel(hit.matched_name_type)}</span>
        </span>
      </td>
      <td className="screening-tier1">
        <dl className="kv screening-scores">
          <Score
            label="Trùng từ (token set)"
            field="token_set"
            meaning="tỷ lệ token_set_ratio của rapidfuzz giữa hai tên đã chuẩn hoá, thang 0 đến 100"
            value={formatNumber(hit.token_set)}
          />
          <Score
            label="Jaro-Winkler"
            field="jaro_winkler"
            meaning="100 x độ tương đồng Jaro-Winkler trên khoá tên không phụ thuộc thứ tự từ"
            value={formatNumber(hit.jaro_winkler)}
          />
          <Score
            label="So khớp mờ"
            field="fuzzy_score"
            meaning="trung bình có trọng số của token_set và jaro_winkler, thang 0 đến 100"
            value={formatNumber(hit.fuzzy_score)}
          />
        </dl>
      </td>
      <td className="screening-tier2">
        <dl className="kv screening-scores">
          <Score
            label="Độ phủ"
            field="coverage"
            meaning="tỷ lệ từ trùng khớp có trọng số IDF (từ hiếm nặng hơn), lấy phía thấp hơn, thang 0 đến 1"
            value={formatNumber(hit.coverage)}
          />
          <Score
            label="Điểm tên"
            field="name_score"
            meaning="so khớp mờ nhân độ phủ, trước khi trừ điểm vì lệch định danh"
            value={formatNumber(hit.name_score)}
          />
          <Score
            label="Lệch năm sinh"
            field="dob_gap_years"
            meaning="số năm chênh giữa năm sinh của khách hàng và của mục danh sách; trống khi một bên không có năm sinh"
            value={hit.dob_gap_years === null ? DASH : `${formatNumber(hit.dob_gap_years)} năm`}
          />
        </dl>
        {/* The backend's sentence is the audit record: shown unchanged. */}
        <span className="cell-sub screening-reason" lang="en">
          {hit.reason}
        </span>
      </td>
      <td
        className="num screening-final"
        title="final_score: điểm tên sau khi trừ điểm vì lệch năm sinh, quốc tịch hoặc giới tính"
      >
        {formatNumber(hit.final_score)}
      </td>
      <td className="screening-system">
        <StatusBadge kind="screeningDecision" value={hit.decision} />
        {hit.case_id ? (
          <span className="cell-sub">
            <Link to={`/cases/${hit.case_id}`}>
              Mở case <span className="code">{hit.case_id}</span>
            </Link>
          </span>
        ) : (
          <span className="cell-sub">Chưa có case</span>
        )}
      </td>
      <td className="screening-human">
        {review && (
          <div className="screening-latest">
            <StatusBadge kind="reviewDecision" value={review.decision} />
            <span className="cell-sub">
              {actorLabel(review.actor)} · {formatDate(review.decided_on)}
            </span>
            <span className="screening-reason">{review.reason}</span>
          </div>
        )}
        <ReviewForm cif={hit.cif} entryId={hit.entry_id} onRecorded={onRecorded} />
      </td>
    </tr>
  );
}
