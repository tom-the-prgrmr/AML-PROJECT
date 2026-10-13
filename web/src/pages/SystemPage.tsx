import type { SampleData, SystemStatus } from "../api/types";
import ApiPanel from "../components/ApiPanel";

export default function SystemPage() {
  return (
    <div>
      <h2>Hệ thống</h2>
      <ApiPanel<SystemStatus> path="/status" title="Trạng thái">
        {(s) => (
          <dl>
            <dt>Backend</dt>
            <dd>{s.backend}</dd>
            <dt>Profile</dt>
            <dd>{s.profile}</dd>
            <dt>Seed</dt>
            <dd>{s.seed}</dd>
            <dt>Ngày tham chiếu</dt>
            <dd>{s.reference_date}</dd>
            <dt>Cờ mock</dt>
            <dd>
              <ul>
                {Object.entries(s.mock).map(([name, on]) => (
                  <li key={name}>
                    {name}: {on ? "bật" : "tắt"}
                  </li>
                ))}
              </ul>
            </dd>
          </dl>
        )}
      </ApiPanel>
      <ApiPanel<SampleData> path="/sample" title="Panel mẫu">
        {(d) => (
          <table>
            <tbody>
              {d.items.map((i) => (
                <tr key={i.id}>
                  <td>{i.id}</td>
                  <td>{i.label}</td>
                  <td>{i.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </ApiPanel>
    </div>
  );
}
