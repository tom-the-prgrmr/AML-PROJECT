export default function Placeholder({ title, detail }: { title: string; detail?: string }) {
  return (
    <div>
      <h2>{title}</h2>
      {detail && <p>{detail}</p>}
      <p className="muted">Chưa triển khai</p>
    </div>
  );
}
