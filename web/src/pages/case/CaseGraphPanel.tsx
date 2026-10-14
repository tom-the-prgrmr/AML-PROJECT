import type { GraphData, GraphMeta } from "../../api/graphTypes";
import ApiPanel from "../../components/ApiPanel";
import CaseGraph from "../../components/CaseGraph";
import { backendLabel, formatDate, formatNumber, graphSourceLabel } from "../../i18n";
import { useCaseHighlight } from "../caseHighlight";

/** Where the graph came from, the window it covers and whether counterparties were cut off. */
function GraphFacts({ meta }: { meta: GraphMeta }) {
  return (
    <div className="toolbar">
      <span className="badge badge-neutral">{graphSourceLabel(meta.graph_source)}</span>
      {meta.backend && <span className="muted">Cơ sở dữ liệu: {backendLabel(meta.backend)}</span>}
      {meta.window_start && (
        <span className="muted">
          Giai đoạn: {formatDate(meta.window_start)} đến {formatDate(meta.window_end)}
        </span>
      )}
      {meta.truncated && (
        <span className="badge badge-warn">
          Hiển thị {formatNumber(meta.counterparties.shown)} / {formatNumber(meta.counterparties.total)}{" "}
          đối tác
        </span>
      )}
    </div>
  );
}

export default function CaseGraphPanel({ caseId }: { caseId: string }) {
  const { highlightIds } = useCaseHighlight();
  return (
    <ApiPanel<GraphData>
      path={`/cases/${encodeURIComponent(caseId)}/graph`}
      title="Đồ thị mạng lưới"
    >
      {(data, meta) => (
        <>
          <GraphFacts meta={meta as unknown as GraphMeta} />
          <CaseGraph nodes={data.nodes} edges={data.edges} highlightIds={highlightIds} />
        </>
      )}
    </ApiPanel>
  );
}
