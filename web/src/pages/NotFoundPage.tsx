import { Link } from "react-router-dom";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";

export default function NotFoundPage() {
  return (
    <>
      <PageHeader title="Không tìm thấy trang" />
      <EmptyState
        title="Địa chỉ này không có trang nào"
        hint={<Link to="/cases">Về hàng đợi case</Link>}
      />
    </>
  );
}
