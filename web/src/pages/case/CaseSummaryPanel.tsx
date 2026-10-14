import type { CaseSummary } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import Markdown from "../../components/Markdown";
import "./insight.css";

/** The stored-data summary of the case. Template text only: it is not a disposition. */
export default function CaseSummaryPanel({ caseId }: { caseId: string }) {
  return (
    <ApiPanel<CaseSummary> path={`/cases/${encodeURIComponent(caseId)}/summary`}>
      {(summary) => (
        <>
          <Markdown text={summary.markdown} />
          <p className="insight-footer">
            Bộ sinh: <span className="code">{summary.generator}</span>, phiên bản{" "}
            <span className="code">{summary.version}</span>
          </p>
        </>
      )}
    </ApiPanel>
  );
}
