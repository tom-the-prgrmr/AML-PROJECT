import type { CaseScores } from "../../api/insightTypes";
import ApiPanel from "../../components/ApiPanel";
import { DASH, featureLabel, formatNumber } from "../../i18n";
import "./insight.css";

/** The priority score of this case from the latest scoring run. The model ranks, it never closes. */
export default function CaseScorePanel({ caseId }: { caseId: string }) {
  return (
    <ApiPanel<CaseScores> path="/cases/scores">
      {(data) => {
        const mine = data.scores.find((s) => s.case_id === caseId);
        if (mine === undefined) {
          return (
            <>
              <p className="score-value">{DASH}</p>
              <p className="muted">Chưa chấm điểm cho lần chạy này</p>
            </>
          );
        }
        return (
          <>
            <div className="score-line">
              <span className="score-value">{formatNumber(mine.score)}</span>
              <span>
                Hạng: <strong>{mine.queue_rank === null ? DASH : formatNumber(mine.queue_rank)}</strong>
                {mine.queue_rank !== null && ` / ${formatNumber(data.queue)}`}
              </span>
              <span className="muted">
                Mô hình: <span className="code">{mine.model_version}</span>
              </span>
            </div>
            {mine.top_features.length > 0 && (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Yếu tố</th>
                      <th className="num">Giá trị</th>
                      <th className="num">Đóng góp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mine.top_features.map((f) => (
                      <tr key={f.feature}>
                        <td>{featureLabel(f.feature)}</td>
                        <td className="num">{formatNumber(f.value)}</td>
                        <td className="num">{formatNumber(f.contribution)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="insight-footer">Mô hình chỉ xếp hạng, không đóng case.</p>
          </>
        );
      }}
    </ApiPanel>
  );
}
