import { Link } from "react-router-dom";
import type { CaseRow } from "../api/types";
import ApiPanel from "../components/ApiPanel";

export default function CasesPage() {
  return (
    <div>
      <h2>Hàng đợi case</h2>
      <ApiPanel<CaseRow[]> path="/cases">
        {(rows) =>
          rows.length === 0 ? (
            <p className="muted">Không có case nào</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Mã case</th>
                  <th>Trạng thái</th>
                  <th>Số alert</th>
                  <th>Nguồn</th>
                  <th>Alert cuối</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.case_id}>
                    <td>
                      <Link to={`/cases/${c.case_id}`}>{c.case_id}</Link>
                    </td>
                    <td>{c.status}</td>
                    <td>{c.alerts}</td>
                    <td>{c.sources.join(", ")}</td>
                    <td>{c.last_alert_ts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </ApiPanel>
    </div>
  );
}
