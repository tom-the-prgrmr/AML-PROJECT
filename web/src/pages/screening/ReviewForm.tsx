import { useState, type FormEvent } from "react";
import { ApiError, apiPost } from "../../api/client";
import type { ReviewDecision } from "../../api/screeningTypes";
import { reviewDecisionLabel } from "../../i18n";

interface Props {
  cif: string;
  entryId: string;
  onRecorded: () => void;
}

const CHOICES: ReviewDecision[] = ["TRUE_MATCH", "FALSE_MATCH"];

/** A person's decision on one hit. It only writes audit_log; the system decision stays as is. */
export default function ReviewForm({ cif, entryId, onRecorded }: Props) {
  const [decision, setDecision] = useState<ReviewDecision>("FALSE_MATCH");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const path = `/screening/hits/${encodeURIComponent(cif)}/${encodeURIComponent(entryId)}/review`;
      await apiPost(path, { decision, reason });
      setReason("");
      setSaved(true);
      onRecorded();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Lỗi không xác định");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="screening-review" onSubmit={submit}>
      <div className="screening-review-row">
        <label>
          <span className="sr-only">Kết luận rà soát</span>
          <select value={decision} onChange={(e) => setDecision(e.target.value as ReviewDecision)}>
            {CHOICES.map((value) => (
              <option key={value} value={value}>
                {reviewDecisionLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="screening-review-reason">
          <span className="sr-only">Lý do (bắt buộc)</span>
          <input
            value={reason}
            placeholder="Lý do (bắt buộc)"
            required
            onChange={(e) => {
              setReason(e.target.value);
              setSaved(false);
            }}
          />
        </label>
        <button type="submit" className="btn-primary" disabled={busy || reason.trim() === ""}>
          {busy ? "Đang ghi..." : "Ghi nhận"}
        </button>
      </div>
      {saved && (
        <span className="cell-sub screening-saved" role="status">
          Đã ghi quyết định vào nhật ký kiểm toán.
        </span>
      )}
      {error && (
        <div className="alert alert-danger" role="alert">
          {error}
        </div>
      )}
    </form>
  );
}
