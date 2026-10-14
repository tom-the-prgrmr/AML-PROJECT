/** Memo labels (GET /memos, POST /memos/{memo_key}/relabel). */
export type MemoCategory =
  | "salary"
  | "loan_repayment"
  | "gambling_like"
  | "crypto_like"
  | "suspicious_wording"
  | "other";

export type MemoMethod = "RULE" | "LLM" | "HUMAN" | "FALLBACK";

export interface MemoLabel {
  memo_key: string;
  memo_norm: string;
  category: string;
  method: string;
  transactions: number;
  model_category: string;
  model_method: string;
}

export interface RelabelResult {
  override_id: number;
  memo_key: string;
  category: string;
  previous_category: string | null;
  previous_method: string | null;
  actor: string;
}
