import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";

export default function Placeholder({ title, detail }: { title: string; detail?: string }) {
  return (
    <>
      <PageHeader title={title} subtitle={detail} />
      <EmptyState title="Chưa triển khai" hint="Trang này sẽ có ở một giai đoạn sau." />
    </>
  );
}
