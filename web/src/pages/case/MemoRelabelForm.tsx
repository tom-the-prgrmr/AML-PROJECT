import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiGet, apiPost } from "../../api/client";
import type { MemoLabel, RelabelResult } from "../../api/memoTypes";
import {
  DASH,
  MEMO_CATEGORY_LABELS,
  errorCodeLabel,
  memoCategoryLabel,
  memoMethodLabel,
} from "../../i18n";
import "./overview.css";

interface Props {
  /** A memo key chosen from the transaction table; `nonce` changes on every pick. */
  prefill: { memoKey: string; nonce: number } | null;
  onRelabelled: () => void;
}

const CATEGORIES = Object.keys(MEMO_CATEGORY_LABELS);
const MAX_NORM = 60;
const MAX_PAGES = 200;
const PAGE_SIZE = 200; // ui.max_page_size

/** Read every page of GET /memos. */
async function loadAllMemos(): Promise<MemoLabel[]> {
  const all: MemoLabel[] = [];
  let offset = 0;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const env = await apiGet<MemoLabel[]>(`/memos?limit=${PAGE_SIZE}&offset=${offset}`);
    all.push(...env.data);
    offset += env.data.length;
    const total = Number(env.meta.total ?? all.length);
    if (env.data.length === 0 || offset >= total) break;
  }
  return all;
}

/** Plain text only (rendered as a text node): the memo cut to 60 characters, its label, its method. */
function optionText(m: MemoLabel): string {
  const norm = m.memo_norm.length > MAX_NORM ? `${m.memo_norm.slice(0, MAX_NORM)}…` : m.memo_norm;
  return `${norm} (${memoCategoryLabel(m.category)}, ${memoMethodLabel(m.method)})`;
}

/** "<previous category>/<previous method>" of a stored relabel. */
function savedFrom(r: RelabelResult): string {
  const cat = r.previous_category === null ? DASH : memoCategoryLabel(r.previous_category);
  const method = r.previous_method === null ? DASH : memoMethodLabel(r.previous_method);
  return `${cat}/${method}`;
}

/** Relabel a memo text. Not a disposition: it neither closes the case nor re-scores it. */
export default function MemoRelabelForm({ prefill, onRelabelled }: Props) {
  const [memos, setMemos] = useState<MemoLabel[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [memoKey, setMemoKey] = useState("");
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [saved, setSaved] = useState<RelabelResult | null>(null);
  const sectionRef = useRef<HTMLElement>(null);

  const loadMemos = useCallback(() => {
    loadAllMemos()
      .then((rows) => {
        setMemos(rows);
        setLoadError(null);
      })
      .catch((e: unknown) => setLoadError(e instanceof ApiError ? e.message : "Lỗi không xác định"));
  }, []);

  useEffect(loadMemos, [loadMemos]);

  useEffect(() => {
    if (prefill === null) return;
    setMemoKey(prefill.memoKey);
    sectionRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [prefill]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const env = await apiPost<RelabelResult>(`/memos/${encodeURIComponent(memoKey)}/relabel`, {
        category,
        reason,
      });
      setReason("");
      setSaved(env.data);
      onRelabelled();
      loadMemos();
    } catch (e: unknown) {
      if (e instanceof ApiError) setError({ code: e.code, message: e.message });
      else setError({ code: "unknown_error", message: "Lỗi không xác định" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" ref={sectionRef}>
      <h2>Gán lại nhãn nội dung giao dịch</h2>
      <form className="form" onSubmit={submit}>
        <label>
          Nội dung giao dịch
          <select value={memoKey} onChange={(e) => setMemoKey(e.target.value)}>
            <option value="">— Chọn nội dung —</option>
            {memos.map((m) => (
              <option key={m.memo_key} value={m.memo_key}>
                {optionText(m)}
              </option>
            ))}
          </select>
          {loadError !== null && <span className="field-hint">{loadError}</span>}
        </label>
        <label>
          Nhãn mới
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {memoCategoryLabel(c)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Lý do
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            maxLength={500}
            aria-describedby="relabel-reason-hint"
          />
          <span className="field-hint" id="relabel-reason-hint">
            Bắt buộc, tối đa 500 ký tự.
          </span>
        </label>
        <p className="field-hint">
          Nhãn memo là feature xếp hạng: không tạo cảnh báo, không đổi case hay disposition;
          feature cập nhật ở lần aml score kế tiếp
        </p>
        <button
          type="submit"
          className="btn-primary"
          disabled={busy || memoKey === "" || reason.trim() === ""}
        >
          {busy ? "Đang ghi..." : "Ghi nhãn"}
        </button>
        {error !== null && (
          <div className="alert alert-danger" role="alert">
            <div>
              <strong className="alert-title">Không ghi được nhãn</strong>
              <code>{error.code}</code> {errorCodeLabel(error.code)}. {error.message}
            </div>
          </div>
        )}
        {saved !== null && (
          <div className="alert form-saved" role="status">
            Đã ghi nhãn #{saved.override_id}: {savedFrom(saved)} → {memoCategoryLabel(saved.category)}
          </div>
        )}
      </form>
    </section>
  );
}
