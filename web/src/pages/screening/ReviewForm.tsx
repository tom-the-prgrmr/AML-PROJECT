import { useState, type FormEvent } from "react";
import { ApiError, apiPost } from "../../api/client";
import type { ReviewDecision } from "../../api/screeningTypes";

interface Props {
  cif: string;
  entryId: string;
  onRecorded: () => void;
}

const CHOICES: { value: ReviewDecision; label: string }[] = [
  { value: "TRUE_MATCH", label: "Khớp thật" },
  { value: "FALSE_MATCH", label: "Khớp giả" },
];

/** A person's decision on one hit. It only writes audit_log; the system decision stays as is. */
export default function ReviewForm({ cif, entryId, onRecorded }: Props) {
  const [decision, setDecision] = useState<ReviewDecision>("FALSE_MATCH");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = `/screening/hits/${encodeURIComponent(cif)}/${encodeURIComponent(entryId)}/review`;
      await apiPost(path, { decision, reason });
      setReason("");
      onRecorded();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Lỗi không xác định");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form screening-review" onSubmit={submit}>
      <select value={decision} onChange={(e) => setDecision(e.target.value as ReviewDecision)}>
        {CHOICES.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
      <input
        value={reason}
        placeholder="Lý do"
        aria-label="Lý do"
        onChange={(e) => setReason(e.target.value)}
      />
      <button type="submit" disabled={busy || reason.trim() === ""}>
        Ghi quyết định
      </button>
      {error && (
        <span className="error-text" role="alert">
          {error}
        </span>
      )}
    </form>
  );
}
