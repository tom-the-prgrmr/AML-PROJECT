import type { GraphData, GraphMeta } from "../../api/graphTypes";
import ApiPanel from "../../components/ApiPanel";
import CaseGraph from "../../components/CaseGraph";
import { useCaseHighlight } from "../caseHighlight";

export default function CaseGraphPanel({ caseId }: { caseId: string }) {
  const { highlightIds } = useCaseHighlight();
  return (
    <ApiPanel<GraphData>
      path={`/cases/${encodeURIComponent(caseId)}/graph`}
      title="Đồ thị mạng lưới"
    >
      {(data, meta) => {
        const m = meta as unknown as GraphMeta;
        return (
          <>
            <p className="muted">
              Nguồn đồ thị: <span className="badge">{m.graph_source}</span>
              {m.window_start && ` - cửa sổ ${m.window_start} đến ${m.window_end}`}
              {m.truncated &&
                ` - hiển thị ${m.counterparties.shown} / ${m.counterparties.total} đối tác`}
            </p>
            <CaseGraph nodes={data.nodes} edges={data.edges} highlightIds={highlightIds} />
          </>
        );
      }}
    </ApiPanel>
  );
}
