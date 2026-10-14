import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown from the backend as safe elements. GFM tables become tables; raw HTML stays plain
 * text (no HTML plugin is installed); links and images never become live elements.
 */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children }) => <span>{children}</span>,
          img: ({ alt }) => (alt ? <span>{alt}</span> : null),
          table: ({ children }) => (
            <div className="table-wrap">
              <table className="data">{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
