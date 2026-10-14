/** Shapes of GET /cases/{id}/graph (see specs/ui-live-pages.md, AC3). */
export type GraphNodeType = "customer" | "account" | "external_account";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  is_subject: boolean;
  golden_customer_id: string | null;
  cif: string | null;
  cifs: { cif: string; full_name: string | null }[] | null;
}

export interface GraphEdge {
  id: string;
  type: "owns" | "transfer";
  source: string;
  target: string;
  txns: number | null;
  vnd: number | null;
  first_ts: string | null;
  last_ts: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphMeta {
  graph_source: string;
  backend?: string;
  counterparties: { total: number; shown: number };
  truncated: boolean;
  window_start: string | null;
  window_end: string | null;
}
