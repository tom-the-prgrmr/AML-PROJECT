import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "../api/graphTypes";
import "./CaseGraph.css";

/** Cytoscape drawing of the case graph; nodes and edges are the `data` of GET /cases/{id}/graph. */
export interface CaseGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightIds: string[];
}

const vnd = (n: number) => `${n.toLocaleString("vi-VN")} VND`;

// Only `data(label)` is drawn, so server text is never interpreted as HTML.
const STYLE: StylesheetJson = [
  {
    selector: "node",
    style: { label: "data(label)", "font-size": 10, "text-valign": "bottom", "text-margin-y": 4 },
  },
  { selector: 'node[type = "customer"]', style: { shape: "round-rectangle", "background-color": "#7b61c9" } },
  { selector: 'node[type = "account"]', style: { shape: "ellipse", "background-color": "#2680c2" } },
  {
    selector: 'node[type = "external_account"]',
    style: { shape: "diamond", "background-color": "#8d8d8d" },
  },
  {
    selector: "node[?is_subject]",
    style: { width: 40, height: 40, "border-width": 4, "border-color": "#b42318", "font-weight": "bold" },
  },
  {
    selector: "edge",
    style: { width: 2, "curve-style": "bezier", "line-color": "#9fb3c8", "target-arrow-color": "#9fb3c8" },
  },
  {
    selector: 'edge[type = "transfer"]',
    style: { "target-arrow-shape": "triangle", label: "data(label)", "font-size": 9, "text-rotation": "autorotate" },
  },
  { selector: 'edge[type = "owns"]', style: { "line-style": "dashed", "target-arrow-shape": "none" } },
  { selector: ".dimmed", style: { opacity: 0.25 } },
  { selector: ".highlighted", style: { "overlay-color": "#f0b429", "overlay-opacity": 0.4, "overlay-padding": 6 } },
  { selector: ":selected", style: { "border-width": 4, "border-color": "#f0b429", "line-color": "#f0b429" } },
];

function elements(nodes: GraphNode[], edges: GraphEdge[]): ElementDefinition[] {
  return [
    ...nodes.map((n) => ({ data: { ...n } })),
    ...edges.map((e) => ({
      data: { ...e, label: e.type === "transfer" && e.vnd !== null ? vnd(e.vnd) : "" },
    })),
  ];
}

function describeNode(n: GraphNode): string {
  const kinds = { customer: "Khách hàng", account: "Tài khoản", external_account: "Tài khoản ngoài hệ thống" };
  const parts = [`${kinds[n.type]} ${n.id}`];
  if (n.is_subject) parts.push("đối tượng của case");
  if (n.golden_customer_id && n.type !== "customer") parts.push(`khách hàng ${n.golden_customer_id}`);
  if (n.cif) parts.push(`CIF ${n.cif}`);
  if (n.cifs) parts.push(n.cifs.map((c) => (c.full_name ? `${c.cif} (${c.full_name})` : c.cif)).join(", "));
  return parts.join(" - ");
}

function describeEdge(e: GraphEdge): string {
  if (e.type === "owns") return `Sở hữu: ${e.source} → ${e.target}`;
  const range = e.first_ts === e.last_ts ? e.first_ts : `${e.first_ts} đến ${e.last_ts}`;
  return `Chuyển khoản ${e.source} → ${e.target}: ${e.txns} giao dịch, ${vnd(e.vnd ?? 0)} (${range})`;
}

/** Marks the highlighted elements, dims the rest and fits the view to them. */
function applyHighlight(cy: Core, ids: string[]) {
  cy.elements().removeClass("highlighted dimmed");
  const found = cy.nodes().filter((n) => ids.includes(n.id()));
  if (found.empty()) {
    cy.fit(undefined, 30);
    return;
  }
  found.addClass("highlighted");
  cy.elements().not(found).addClass("dimmed");
  cy.fit(found, 60);
}

export default function CaseGraph({ nodes, edges, highlightIds }: CaseGraphProps) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const items = useMemo(() => elements(nodes, edges), [nodes, edges]);
  const missing = highlightIds.filter((id) => !nodes.some((n) => n.id === id));

  useEffect(() => {
    if (!box.current) return;
    const cy = cytoscape({ container: box.current, elements: items, style: STYLE, layout: { name: "cose" } });
    cy.on("tap", "node", (ev) => setDetail(describeNode(nodes.find((n) => n.id === ev.target.id())!)));
    cy.on("tap", "edge", (ev) => setDetail(describeEdge(edges.find((e) => e.id === ev.target.id())!)));
    cy.on("tap", (ev) => {
      if (ev.target === cy) setDetail(null);
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [items, nodes, edges]);

  useEffect(() => {
    const cy = cyRef.current;
    if (cy) applyHighlight(cy, highlightIds);
  }, [items, highlightIds]);

  return (
    <div className="case-graph">
      <p className="graph-legend">
        <span>Hình chữ nhật tròn: khách hàng</span>
        <span>Hình tròn: tài khoản</span>
        <span>Hình thoi: tài khoản ngoài hệ thống</span>
        <span>Viền đỏ: đối tượng của case</span>
      </p>
      <div ref={box} className="graph-canvas" data-testid="graph-canvas" />
      {detail && <p className="graph-detail">{detail}</p>}
      {missing.length > 0 && (
        <p className="graph-missing" data-testid="graph-highlight-missing">
          Không có trong đồ thị: {missing.join(", ")}
        </p>
      )}
    </div>
  );
}
