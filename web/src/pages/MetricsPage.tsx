import PageHeader from "../components/PageHeader";
import AutoClearedPanel from "./metrics/AutoClearedPanel";
import DetectionsPanel from "./metrics/DetectionsPanel";
import FunnelPanel from "./metrics/FunnelPanel";
import SuppressionPanel from "./metrics/SuppressionPanel";
import "./metrics/metrics.css";

/** Four independent panels. Each is read from its own endpoint and no figure is summed across them. */
export default function MetricsPage() {
  return (
    <div className="metrics-panels">
      <PageHeader
        title="Chỉ số"
        subtitle="Số liệu đọc từ lần chạy thật của hệ thống. Giờ tiết kiệm chỉ là ước tính theo giả định thời gian xử lý mỗi cảnh báo."
      />
      <FunnelPanel />
      <DetectionsPanel />
      <AutoClearedPanel />
      <SuppressionPanel />
    </div>
  );
}
