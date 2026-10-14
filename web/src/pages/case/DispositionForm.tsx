import { useState, type FormEvent } from "react";
import { ApiError, apiPost } from "../../api/client";
import type { DispositionValue } from "../../api/types";
import { dispositionLabel } from "../../i18n";
import "./overview.css";

interface Props {
  caseId: string;
  onRecorded: () => void;
}

/** The values the endpoint accepts; the visible text comes from the Vietnamese dictionary. */
const OPTIONS: DispositionValue[] = ["SUSPICIOUS", "FALSE_POSITIVE"];

export default function DispositionForm({ caseId, onRecorded }: Props) {
  const [disposition, setDisposition] = useState<DispositionValue>("SUSPICIOUS");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<DispositionValue | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      await apiPost(`/cases/${encodeURIComponent(caseId)}/disposition`, { disposition, reason });
      setReason("");
      setSaved(disposition);
      onRecorded();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Lỗi không xác định");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Ghi quyết định của điều tra viên</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Quyết định
          <select
            value={disposition}
            onChange={(e) => setDisposition(e.target.value as DispositionValue)}
          >
            {OPTIONS.map((value) => (
              <option key={value} value={value}>
                {dispositionLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Lý do
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            aria-describedby="disposition-reason-hint"
          />
          <span className="field-hint" id="disposition-reason-hint">
            Bắt buộc. Lý do được lưu nguyên văn vào nhật ký kiểm toán cùng tên người quyết định.
          </span>
        </label>
        <button type="submit" className="btn-primary" disabled={busy || reason.trim() === ""}>
          {busy ? "Đang ghi..." : "Ghi quyết định"}
        </button>
        {error !== null && (
          <div className="alert alert-danger" role="alert">
            <div>
              <strong className="alert-title">Không ghi được quyết định</strong>
              {error}
            </div>
          </div>
        )}
        {saved !== null && (
          <div className="alert form-saved" role="status">
            Đã ghi quyết định “{dispositionLabel(saved)}”. Trạng thái case sẽ được cập nhật ở lần
            chạy kế tiếp.
          </div>
        )}
      </form>
    </section>
  );
}
