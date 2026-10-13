import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CaseDetailPage from "./pages/CaseDetailPage";
import CasesPage from "./pages/CasesPage";
import NotFoundPage from "./pages/NotFoundPage";
import Placeholder from "./pages/Placeholder";
import SystemPage from "./pages/SystemPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        <Route path="/screening" element={<Placeholder title="Rà soát screening" />} />
        <Route path="/data-quality" element={<Placeholder title="Chất lượng dữ liệu" />} />
        <Route path="/benchmark" element={<Placeholder title="Benchmark" />} />
        <Route path="/metrics" element={<Placeholder title="Chỉ số" />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
