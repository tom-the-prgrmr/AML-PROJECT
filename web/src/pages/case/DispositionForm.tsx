import { useState, type FormEvent } from "react";
import { ApiError, apiPost } from "../../api/client";
import type { DispositionValue } from "../../api/types";

interface Props {
  caseId: string;
  onRecorded: () => void;
}

export default function DispositionForm({ caseId, onRecorded }: Props) {
  const [disposition, setDisposition] = useState<DispositionValue>("SUSPICIOUS");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/cases/${encodeURIComponent(caseId)}/disposition`, { disposition, reason });
      setReason("");
      onRecorded();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Lỗi không xác định");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Quyết định của điều tra viên</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Quyết định
          <select
            value={disposition}
            onChange={(e) => setDisposition(e.target.value as DispositionValue)}
          >
            <option value="SUSPICIOUS">SUSPICIOUS</option>
            <option value="FALSE_POSITIVE">FALSE_POSITIVE</option>
          </select>
        </label>
        <label>
          Lý do
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
        </label>
        <button type="submit" disabled={busy || reason.trim() === ""}>
          Ghi quyết định
        </button>
        {error !== null && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
