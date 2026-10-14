import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import BenchmarkPage from "./pages/BenchmarkPage";
import CaseDetailPage from "./pages/CaseDetailPage";
import CasesPage from "./pages/CasesPage";
import DataQualityPage from "./pages/DataQualityPage";
import NotFoundPage from "./pages/NotFoundPage";
import Placeholder from "./pages/Placeholder";
import ScreeningPage from "./pages/ScreeningPage";
import SystemPage from "./pages/SystemPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        <Route path="/screening" element={<ScreeningPage />} />
        <Route path="/data-quality" element={<DataQualityPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
        <Route path="/metrics" element={<Placeholder title="Chỉ số" />} />
        <Route path="/system" element={<SystemPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
