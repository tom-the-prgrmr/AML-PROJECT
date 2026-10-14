import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import ApiPanel from "../components/ApiPanel";
import type { CaseDetail } from "../api/types";
import { CaseHighlightContext } from "./caseHighlight";
import CaseEnrichment from "./case/CaseEnrichment";
import CaseEvidence from "./case/CaseEvidence";
import CaseGraphPanel from "./case/CaseGraphPanel";
import CaseHeader from "./case/CaseHeader";
import DispositionForm from "./case/DispositionForm";
import TracePanel from "./case/TracePanel";

interface Props {
  scoreSlot?: ReactNode;
  summarySlot?: ReactNode;
  assistantSlot?: ReactNode;
}

interface SlotProps {
  testId: string;
  title: string;
  children?: ReactNode;
}

/** An empty titled frame; the content comes from another spec through the page props. */
function Slot({ testId, title, children }: SlotProps) {
  return (
    <div className="slot" data-testid={testId}>
      <h3>{title}</h3>
      {children ?? <span className="empty-slot">Chưa có nội dung</span>}
    </div>
  );
}

/** Keyed by case id: going to another case starts from a clean page (no highlight, no trace). */
export default function CaseDetailPage(props: Props) {
  const { caseId = "" } = useParams();
  return <CaseDetailBody key={caseId} caseId={caseId} {...props} />;
}

function CaseDetailBody({
  caseId,
  scoreSlot,
  summarySlot,
  assistantSlot,
}: Props & { caseId: string }) {
  const [highlightIds, setHighlightIds] = useState<string[]>([]);
  const setHighlight = useCallback((ids: string[]) => setHighlightIds(ids), []);
  const clearHighlight = useCallback(() => setHighlightIds([]), []);
  const highlight = useMemo(
    () => ({ highlightIds, setHighlight, clearHighlight }),
    [highlightIds, setHighlight, clearHighlight],
  );

  return (
    <CaseHighlightContext.Provider value={highlight}>
      <ApiPanel<CaseDetail> path={`/cases/${encodeURIComponent(caseId)}`}>
        {(detail, _meta, reload) => (
          <div>
            <CaseHeader detail={detail} />
            <Slot testId="slot-case-score" title="Điểm ưu tiên">
              {scoreSlot}
            </Slot>
            <Slot testId="slot-case-summary" title="Tóm tắt case">
              {summarySlot}
            </Slot>
            <CaseEnrichment detail={detail} />
            <CaseEvidence detail={detail} />
            <DispositionForm caseId={detail.case_id} onRecorded={reload} />
            <div className="two-col">
              <CaseGraphPanel caseId={detail.case_id} />
              <Slot testId="slot-assistant" title="Trợ lý điều tra">
                {assistantSlot}
              </Slot>
            </div>
            <TracePanel accounts={detail.enrichment.linked_cifs.accounts} />
          </div>
        )}
      </ApiPanel>
    </CaseHighlightContext.Provider>
  );
}
