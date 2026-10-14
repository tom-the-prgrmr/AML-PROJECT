/** Previous / next over a paged list endpoint; shows which rows of the total are on screen. */
export default function Pager(props: {
  offset: number;
  limit: number;
  total: number;
  shown: number;
  onPage: (offset: number) => void;
}) {
  const { offset, limit, total, shown, onPage } = props;
  const end = offset + shown;
  return (
    <nav className="pager" aria-label="Phân trang">
      <span className="pager-range">
        {total === 0 ? 0 : offset + 1}-{end} / {total}
      </span>
      <button type="button" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>
        Trang trước
      </button>
      <button type="button" disabled={end >= total} onClick={() => onPage(offset + limit)}>
        Trang sau
      </button>
    </nav>
  );
}
