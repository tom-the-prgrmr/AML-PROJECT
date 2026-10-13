import { useParams } from "react-router-dom";
import Placeholder from "./Placeholder";

export default function CaseDetailPage() {
  const { caseId } = useParams();
  return <Placeholder title="Chi tiết case" detail={caseId} />;
}
