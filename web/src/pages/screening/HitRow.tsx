import { Link } from "react-router-dom";
import type { Hit } from "../../api/screeningTypes";
import ReviewForm from "./ReviewForm";

interface Props {
  hit: Hit;
  onRecorded: () => void;
}

const BADGE: Record<Hit["decision"], string> = {
  ALERT: "badge badge-bad",
  REVIEW: "badge badge-warn",
  AUTO_CLEARED: "badge badge-ok",
};

const MATCH_LABEL = { TRUE_MATCH: "Khớp thật", FALSE_MATCH: "Khớp giả" } as const;

export default function HitRow({ hit, onRecorded }: Props) {
  const c = hit.customer;
  return (
    <tr>
      <td>
        {hit.cif}:{hit.entry_id}
        <br />
        {c ? (
          <span className="muted">
            {c.full_name} ({c.birth_year ?? "?"}) {c.id_type} {c.id_number}
          </span>
        ) : (
          <span className="muted">Không còn khách hàng</span>
        )}
      </td>
      <td>
        {hit.matched_name}
        <br />
        <span className="muted">
          {hit.list_type} / {hit.matched_name_type}
        </span>
      </td>
      <td className="screening-why">
        Tier 1: token_set {hit.token_set}, jaro_winkler {hit.jaro_winkler}, fuzzy {hit.fuzzy_score}
      </td>
      <td className="screening-why">
        Tier 2: coverage {hit.coverage}, name {hit.name_score}, dob gap {hit.dob_gap_years ?? "-"}
        <br />
        <span className="muted">{hit.reason}</span>
      </td>
      <td>{hit.final_score}</td>
      <td>
        <span className={BADGE[hit.decision]}>{hit.decision}</span>
        <br />
        {hit.case_id ? <Link to={`/cases/${hit.case_id}`}>{hit.case_id}</Link> : "-"}
      </td>
      <td>
        {hit.review && (
          <p>
            <strong>{MATCH_LABEL[hit.review.decision]}</strong> - {hit.review.actor},{" "}
            {hit.review.decided_on}: {hit.review.reason}
          </p>
        )}
        <ReviewForm cif={hit.cif} entryId={hit.entry_id} onRecorded={onRecorded} />
      </td>
    </tr>
  );
}
