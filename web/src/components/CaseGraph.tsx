import cytoscape, {
  type Core,
  type ElementDefinition,
  type LayoutOptions,
  type StylesheetJson,
} from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode, GraphNodeType } from "../api/graphTypes";
import {
  formatDateTime,
  formatNumber,
  formatVnd,
  graphEdgeTypeLabel,
  graphNodeTypeLabel,
} from "../i18n";
import "./CaseGraph.css";

/** Cytoscape drawing of the case graph; nodes and edges are the `data` of GET /cases/{id}/graph. */
export interface CaseGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightIds: string[];
}

/*
 * Graph palette. Cytoscape paints on a canvas and cannot read CSS variables, so the colours of the
 * drawing are named here once, mirroring the tokens of styles.css. This block is the only place
 * with hex values; the stylesheet below and the legend both read from it, so they cannot drift.
 */
const PALETTE = {
  brand: "#d91a21", // --color-primary: the subject of the case, highlights, selection
  brandDark: "#b3121a", // --color-primary-hover: border of the subject
  customer: "#3f3f46", // --color-neutral-fg: other customers
  customerBorder: "#18181b", // --color-text
  account: "#64748b", // calm blue-grey: accounts inside the bank
  accountBorder: "#475569",
  external: "#fffbeb", // --color-warning-bg: accounts outside the bank are outlined, not filled
  externalBorder: "#b45309", // amber outline
  transfer: "#71717a", // mid-grey transfer edges
  owns: "#d4d4d8", // --color-border-strong: ownership edges stay in the background
  text: "#18181b", // --color-text
  textMuted: "#52525b", // --color-text-muted
  labelBg: "#ffffff", // --color-surface: plate behind a label so it stays legible over edges
} as const;

/** One shape per node type, so the type never depends on colour alone. */
interface NodeLook {
  shape: "round-rectangle" | "ellipse" | "diamond";
  fill: string;
  border: string;
}
const NODE_LOOK: Record<GraphNodeType, NodeLook> = {
  customer: { shape: "round-rectangle", fill: PALETTE.customer, border: PALETTE.customerBorder },
  account: { shape: "ellipse", fill: PALETTE.account, border: PALETTE.accountBorder },
  external_account: { shape: "diamond", fill: PALETTE.external, border: PALETTE.externalBorder },
};
const NODE_TYPES = Object.keys(NODE_LOOK) as GraphNodeType[];
const SUBJECT_LOOK: NodeLook = { shape: "round-rectangle", fill: PALETTE.brand, border: PALETTE.brandDark };
const FONT = "Inter, Segoe UI, system-ui, sans-serif";

const labelPlate = {
  "text-background-color": PALETTE.labelBg,
  "text-background-opacity": 0.85,
  "text-background-padding": "2px",
  "text-background-shape": "roundrectangle",
} as const;

// Only `data(label)` is drawn, so server text is never interpreted as HTML. Later rules win.
const STYLE: StylesheetJson = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      width: 30,
      height: 30,
      "border-width": 1.5,
      "font-family": FONT,
      "font-size": 13,
      color: PALETTE.text,
      "text-valign": "bottom",
      "text-margin-y": 5,
      ...labelPlate,
    },
  },
  ...NODE_TYPES.map((type) => ({
    selector: `node[type = "${type}"]`,
    style: {
      shape: NODE_LOOK[type].shape,
      "background-color": NODE_LOOK[type].fill,
      "border-color": NODE_LOOK[type].border,
    },
  })),
  { selector: 'node[type = "external_account"]', style: { "border-width": 2 } },
  {
    selector: "node[?is_subject]",
    style: {
      width: 46,
      height: 46,
      "background-color": SUBJECT_LOOK.fill,
      "border-color": SUBJECT_LOOK.border,
      "border-width": 3,
      "font-size": 14,
      "font-weight": "bold",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "curve-style": "bezier",
      "line-color": PALETTE.transfer,
      "target-arrow-color": PALETTE.transfer,
    },
  },
  {
    selector: 'edge[type = "transfer"]',
    style: {
      "target-arrow-shape": "triangle",
      label: "data(label)",
      "font-family": FONT,
      "font-size": 12,
      color: PALETTE.textMuted,
      "text-rotation": "autorotate",
      ...labelPlate,
    },
  },
  {
    selector: 'edge[type = "owns"]',
    style: { "line-style": "dashed", "line-color": PALETTE.owns, "target-arrow-shape": "none" },
  },
  { selector: ".dimmed", style: { opacity: 0.2 } },
  {
    selector: ".highlighted",
    style: {
      "border-color": PALETTE.brand,
      "border-width": 3,
      "underlay-color": PALETTE.brand,
      "underlay-opacity": 0.18,
      "underlay-padding": 8,
      "underlay-shape": "ellipse",
    },
  },
  { selector: "node:selected", style: { "border-color": PALETTE.brand, "border-width": 4 } },
  {
    selector: "edge:selected",
    style: { width: 3, "line-color": PALETTE.brand, "target-arrow-color": PALETTE.brand },
  },
];

function elements(nodes: GraphNode[], edges: GraphEdge[]): ElementDefinition[] {
  return [
    ...nodes.map((n) => ({ data: { ...n } })),
    ...edges.map((e) => ({
      data: { ...e, label: e.type === "transfer" && e.vnd !== null ? `${formatVnd(e.vnd)} VND` : "" },
    })),
  ];
}

/**
 * A force layout tuned for small case graphs: nodes keep their distance (labels included), edges
 * stay long enough for the VND labels, and the drawing is spread over the canvas instead of
 * piled in the middle.
 */
const LAYOUT: LayoutOptions = {
  name: "cose",
  animate: false,
  padding: 40,
  nodeDimensionsIncludeLabels: true,
  nodeRepulsion: () => 14000,
  idealEdgeLength: () => 110,
  edgeElasticity: () => 80,
  gravity: 0.2,
  numIter: 2000,
  componentSpacing: 90,
};

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

/** A node mark of the legend, drawn with the shape and colours of the Cytoscape style. */
function NodeMark({ look }: { look: NodeLook }) {
  const paint = { fill: look.fill, stroke: look.border, strokeWidth: 1.5 };
  return (
    <svg className="graph-legend-mark" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      {look.shape === "ellipse" && <circle cx="8" cy="8" r="6.5" {...paint} />}
      {look.shape === "diamond" && <polygon points="8,1 15,8 8,15 1,8" {...paint} />}
      {look.shape === "round-rectangle" && <rect x="1.5" y="1.5" width="13" height="13" rx="3" {...paint} />}
    </svg>
  );
}

function EdgeMark({ color, dashed, arrow }: { color: string; dashed?: boolean; arrow?: boolean }) {
  return (
    <svg className="graph-legend-mark" viewBox="0 0 28 16" width="28" height="16" aria-hidden="true">
      <line
        x1="1"
        y1="8"
        x2={arrow ? 21 : 27}
        y2="8"
        stroke={color}
        strokeWidth="2"
        strokeDasharray={dashed ? "4 3" : undefined}
      />
      {arrow && <polygon points="20,4 27,8 20,12" fill={color} />}
    </svg>
  );
}

/** Legend of the drawing: every entry is a shape plus its Vietnamese label. */
function Legend() {
  return (
    <ul className="graph-legend" aria-label="Chú giải đồ thị">
      <li>
        <NodeMark look={SUBJECT_LOOK} />
        Đối tượng của hồ sơ
      </li>
      {NODE_TYPES.map((type) => (
        <li key={type}>
          <NodeMark look={NODE_LOOK[type]} />
          {graphNodeTypeLabel(type)}
        </li>
      ))}
      <li>
        <EdgeMark color={PALETTE.transfer} arrow />
        {graphEdgeTypeLabel("transfer")} (tổng tiền, VND)
      </li>
      <li>
        <EdgeMark color={PALETTE.owns} dashed />
        {graphEdgeTypeLabel("owns")}
      </li>
    </ul>
  );
}

type Detail = { kind: "node"; node: GraphNode } | { kind: "edge"; edge: GraphEdge };

function NodeDetail({ node }: { node: GraphNode }) {
  return (
    <dl className="kv">
      <dt>Loại</dt>
      <dd>{graphNodeTypeLabel(node.type)}</dd>
      <dt>Mã</dt>
      <dd className="code">{node.id}</dd>
      {node.is_subject && (
        <>
          <dt>Vai trò</dt>
          <dd>
            <span className="badge badge-bad">Đối tượng của hồ sơ</span>
          </dd>
        </>
      )}
      {node.golden_customer_id && node.type !== "customer" && (
        <>
          <dt>Khách hàng sở hữu</dt>
          <dd className="code">{node.golden_customer_id}</dd>
        </>
      )}
      {node.cif && (
        <>
          <dt>Mã CIF</dt>
          <dd className="code">{node.cif}</dd>
        </>
      )}
      {node.cifs && node.cifs.length > 0 && (
        <>
          <dt>Các CIF của khách hàng</dt>
          <dd>
            {node.cifs.map((c) => (
              <span key={c.cif} className="graph-detail-line">
                <span className="code">{c.cif}</span>
                {c.full_name && ` - ${c.full_name}`}
              </span>
            ))}
          </dd>
        </>
      )}
    </dl>
  );
}

function EdgeDetail({ edge }: { edge: GraphEdge }) {
  const transfer = edge.type === "transfer";
  return (
    <dl className="kv">
      <dt>Loại quan hệ</dt>
      <dd>{graphEdgeTypeLabel(edge.type)}</dd>
      <dt>{transfer ? "Tài khoản chuyển" : "Khách hàng"}</dt>
      <dd className="code">{edge.source}</dd>
      <dt>{transfer ? "Tài khoản nhận" : "Tài khoản"}</dt>
      <dd className="code">{edge.target}</dd>
      {transfer && (
        <>
          <dt>Số giao dịch</dt>
          <dd>{formatNumber(edge.txns)}</dd>
          <dt>Tổng tiền (VND)</dt>
          <dd>{formatVnd(edge.vnd)}</dd>
          <dt>Giao dịch đầu</dt>
          <dd>{formatDateTime(edge.first_ts)}</dd>
          <dt>Giao dịch cuối</dt>
          <dd>{formatDateTime(edge.last_ts)}</dd>
        </>
      )}
    </dl>
  );
}

export default function CaseGraph({ nodes, edges, highlightIds }: CaseGraphProps) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const items = useMemo(() => elements(nodes, edges), [nodes, edges]);
  const missing = highlightIds.filter((id) => !nodes.some((n) => n.id === id));

  useEffect(() => {
    if (!box.current) return;
    setDetail(null); // a detail of the previous graph must not stay under a new one
    const cy = cytoscape({
      container: box.current,
      elements: items,
      style: STYLE,
      layout: LAYOUT,
      // Without a cap, fitting a graph of one or two nodes blows them up to fill the whole canvas.
      minZoom: 0.25,
      maxZoom: 1.6,
      wheelSensitivity: 0.2,
    });
    cy.on("tap", "node", (ev) => {
      const node = nodes.find((n) => n.id === ev.target.id());
      setDetail(node ? { kind: "node", node } : null);
    });
    cy.on("tap", "edge", (ev) => {
      const edge = edges.find((e) => e.id === ev.target.id());
      setDetail(edge ? { kind: "edge", edge } : null);
    });
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
      <Legend />
      <div ref={box} className="graph-canvas" data-testid="graph-canvas" />
      {detail ? (
        <div className="graph-detail">
          <h3>{detail.kind === "node" ? "Chi tiết nút" : "Chi tiết liên kết"}</h3>
          {detail.kind === "node" ? <NodeDetail node={detail.node} /> : <EdgeDetail edge={detail.edge} />}
        </div>
      ) : (
        <p className="muted graph-hint">Bấm vào một nút hoặc một liên kết để xem chi tiết.</p>
      )}
      {missing.length > 0 && (
        <p className="graph-missing" data-testid="graph-highlight-missing">
          Không có trong đồ thị: <span className="code">{missing.join(", ")}</span>
        </p>
      )}
    </div>
  );
}
