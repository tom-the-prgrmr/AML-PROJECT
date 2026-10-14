import type { SampleData, SystemStatus } from "../api/types";
import ApiPanel from "../components/ApiPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import { BADGE_CLASS } from "../components/tone";
import { backendLabel, formatDate, formatNumber, mockFlagLabel } from "../i18n";

function CaseRun({ run }: { run: SystemStatus["case_run"] }) {
  if (run === null) return <span className="muted">Chưa có lần chạy case nào</span>;
  return (
    <dl className="kv">
      <div>
        <dt>Mã lần chạy</dt>
        <dd>
          <span className="code">{run.run_id}</span>
        </dd>
      </div>
      <div>
        <dt>Ngày dữ liệu</dt>
        <dd>{formatDate(run.as_of)}</dd>
      </div>
      <div>
        <dt>Số case</dt>
        <dd>{formatNumber(run.cases)}</dd>
      </div>
    </dl>
  );
}

function MockFlags({ mock }: { mock: Record<string, boolean> }) {
  const flags = Object.entries(mock);
  if (flags.length === 0) return <span className="muted">Không có cờ dữ liệu mẫu nào</span>;
  return (
    <ul>
      {flags.map(([name, on]) => (
        <li key={name}>
          {mockFlagLabel(name)}{" "}
          <span className={on ? BADGE_CLASS.warning : BADGE_CLASS.neutral}>{on ? "Bật" : "Tắt"}</span>
        </li>
      ))}
    </ul>
  );
}

function sampleValue(value: number | string): string {
  return typeof value === "number" ? formatNumber(value) : value;
}

export default function SystemPage() {
  return (
    <>
      <PageHeader
        title="Hệ thống"
        subtitle="Cấu hình đang chạy của máy chủ và các phần đang dùng dữ liệu mẫu."
      />
      <ApiPanel<SystemStatus> path="/status" title="Trạng thái">
        {(s) => (
          <dl className="kv">
            <div>
              <dt>Cơ sở dữ liệu</dt>
              <dd>{backendLabel(s.backend)}</dd>
            </div>
            <div>
              <dt>Bộ dữ liệu</dt>
              <dd>
                <span className="code">{s.profile}</span>
              </dd>
            </div>
            <div>
              <dt>Hạt giống ngẫu nhiên</dt>
              <dd>
                <span className="code">{s.seed}</span>
              </dd>
            </div>
            <div>
              <dt>Ngày tham chiếu</dt>
              <dd>{formatDate(s.reference_date)}</dd>
            </div>
            <div>
              <dt>Lần chạy case gần nhất</dt>
              <dd>
                <CaseRun run={s.case_run} />
              </dd>
            </div>
            <div>
              <dt>Dữ liệu giả lập</dt>
              <dd>
                <MockFlags mock={s.mock} />
              </dd>
            </div>
          </dl>
        )}
      </ApiPanel>
      <ApiPanel<SampleData> path="/sample" title="Panel mẫu">
        {(d) =>
          d.items.length === 0 ? (
            <EmptyState title="Không có dòng nào" />
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Mã</th>
                    <th>Nhãn</th>
                    <th className="num">Giá trị</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((i) => (
                    <tr key={i.id}>
                      <td>
                        <span className="code">{i.id}</span>
                      </td>
                      <td>{i.label}</td>
                      <td className="num">{sampleValue(i.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </ApiPanel>
    </>
  );
}
