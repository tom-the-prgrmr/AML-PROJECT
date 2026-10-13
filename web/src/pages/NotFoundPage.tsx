import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div>
      <h2>Không tìm thấy trang</h2>
      <p>
        <Link to="/cases">Về hàng đợi case</Link>
      </p>
    </div>
  );
}
