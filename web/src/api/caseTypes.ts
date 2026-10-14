/** Rows of the two case reads that the shared types file does not cover. */

/** One row of GET /cases/{id}/transactions (never carries device or IP). */
export interface CaseTransaction {
  txn_id: string;
  txn_ts: string;
  from_account_id: string | null;
  to_account_id: string | null;
  amount_vnd: number;
  channel: string | null;
  memo: string | null;
  counterparty_name: string | null;
  item_keys: string[];
}

/** One row of GET /cases/{id}/subjects: masked or full by role; extra columns are optional. */
export interface CaseSubject {
  cif: string;
  full_name: string | null;
  [column: string]: string | number | null;
}
