import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import ApiPanel from "../components/ApiPanel";
import type { CaseDetail } from "../api/types";
import { CaseHighlightContext } from "./caseHighlight";
import AssistantPanel from "./case/AssistantPanel";
import CaseScorePanel from "./case/CaseScorePanel";
import CaseSummaryPanel from "./case/CaseSummaryPanel";
import CaseEnrichment from "./case/CaseEnrichment";
import CaseEvidence from "./case/CaseEvidence";
import CaseGraphPanel from "./case/CaseGraphPanel";
import CaseHeader from "./case/CaseHeader";
import DispositionForm from "./case/DispositionForm";
import MemoRelabelForm from "./case/MemoRelabelForm";
import TracePanel from "./case/TracePanel";

interface SlotProps {
  testId: string;
  title: string;
  children?: ReactNode;
}

/** A titled frame for one panel of the case page. */
function Slot({ testId, title, children }: SlotProps) {
  return (
    <div className="slot" data-testid={testId}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

/** Keyed by case id: going to another case starts from a clean page (no highlight, no trace). */
export default function CaseDetailPage() {
  const { caseId = "" } = useParams();
  return <CaseDetailBody key={caseId} caseId={caseId} />;
}

function CaseDetailBody({ caseId }: { caseId: string }) {
  const [highlightIds, setHighlightIds] = useState<string[]>([]);
  const setHighlight = useCallback((ids: string[]) => setHighlightIds(ids), []);
  const clearHighlight = useCallback(() => setHighlightIds([]), []);
  const [txnVersion, setTxnVersion] = useState(0);
  const [prefill, setPrefill] = useState<{ memoKey: string; nonce: number } | null>(null);
  const pickMemo = useCallback(
    (memoKey: string) => setPrefill((p) => ({ memoKey, nonce: (p?.nonce ?? 0) + 1 })),
    [],
  );
  const reloadTxns = useCallback(() => setTxnVersion((v) => v + 1), []);
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
              <CaseScorePanel caseId={detail.case_id} />
            </Slot>
            <Slot testId="slot-case-summary" title="Tóm tắt case">
              <CaseSummaryPanel caseId={detail.case_id} />
            </Slot>
            <CaseEnrichment detail={detail} />
            <CaseEvidence detail={detail} txnVersion={txnVersion} onRelabel={pickMemo} />
            <MemoRelabelForm prefill={prefill} onRelabelled={reloadTxns} />
            <DispositionForm caseId={detail.case_id} onRecorded={reload} />
            <div className="two-col">
              <CaseGraphPanel caseId={detail.case_id} />
              <Slot testId="slot-assistant" title="Trợ lý điều tra">
                <AssistantPanel caseId={detail.case_id} />
              </Slot>
            </div>
            <TracePanel accounts={detail.enrichment.linked_cifs.accounts} />
          </div>
        )}
      </ApiPanel>
    </CaseHighlightContext.Provider>
  );
}
