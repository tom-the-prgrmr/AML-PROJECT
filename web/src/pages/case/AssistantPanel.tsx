import { useState } from "react";
import { ApiError, apiPost } from "../../api/client";
import type {
  Answer,
  Citation,
  DraftNarrative,
  FeedbackResult,
  Rating,
  Typologies,
  TypologyMatch,
} from "../../api/insightTypes";
import type { Envelope } from "../../api/types";
import ApiPanel from "../../components/ApiPanel";
import EmptyState from "../../components/EmptyState";
import Markdown from "../../components/Markdown";
import RuleLabel from "../../components/RuleLabel";
import {
  answerStatusLabel,
  channelLabel,
  citationKindLabel,
  dash,
  errorCodeLabel,
  formatDateTime,
  formatVnd,
  ratingLabel,
  typologyLabel,
} from "../../i18n";
import { useCaseHighlight } from "../caseHighlight";
import "./insight.css";

const QUESTION_MAX = 1000;
const COMMENT_MAX = 1000;

type Post<T> =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "ok"; envelope: Envelope<T> }
  | { kind: "error"; code: string; message: string };

/** Run one POST at a time from a button; the result or the error stays on screen. */
function usePost<T>(): [Post<T>, (path: string, body: unknown) => Promise<void>] {
  const [state, setState] = useState<Post<T>>({ kind: "idle" });
  async function run(path: string, body: unknown): Promise<void> {
    setState({ kind: "busy" });
    try {
      setState({ kind: "ok", envelope: await apiPost<T>(path, body) });
    } catch (e: unknown) {
      const code = e instanceof ApiError ? e.code : "unknown_error";
      const message = e instanceof ApiError ? e.message : "Lỗi không xác định";
      setState({ kind: "error", code, message });
    }
  }
  return [state, run];
}

/** The error of a POST: 503 says what to start, 502 shows the model's own message. */
function PostError({ code, message }: { code: string; message: string }) {
  return (
    <div className="alert alert-danger" role="alert">
      <div>
        {code === "unavailable" ? (
          <strong className="alert-title">Trợ lý chưa sẵn sàng (cần Ollama và Neo4j)</strong>
        ) : (
          <>
            <strong className="alert-title">{errorCodeLabel(code)}</strong>
            <code>{code}</code> {message}
          </>
        )}
      </div>
    </div>
  );
}

/** `[n]` buttons; a click selects the citation and, when it names graph nodes, highlights them. */
function CitationList({ citations }: { citations: Citation[] }) {
  const { setHighlight } = useCaseHighlight();
  const [picked, setPicked] = useState<Citation | null>(null);
  if (citations.length === 0) return null;
  return (
    <div>
      <div className="insight-actions" role="group" aria-label="Trích dẫn">
        {citations.map((c) => (
          <button
            key={c.n}
            type="button"
            className="insight-citation"
            aria-pressed={picked?.n === c.n}
            aria-label={`Trích dẫn ${c.n}: ${citationKindLabel(c.kind)} ${c.id}`}
            onClick={() => {
              setPicked(c);
              if (c.node_ids.length > 0) setHighlight(c.node_ids);
            }}
          >
            [{c.n}]
          </button>
        ))}
      </div>
      {picked !== null && (
        <div className="citation-detail">
          {citationKindLabel(picked.kind)}: <span className="code">{picked.id}</span>
          {picked.excerpt !== null && <p className="free-text">{picked.excerpt}</p>}
        </div>
      )}
    </div>
  );
}

function SentenceItem(props: { text: string; supported: boolean; marks: number[] }) {
  const { text, supported, marks } = props;
  return (
    <li className={supported ? "answer-sentence" : "answer-sentence unverified"}>
      {text}
      {marks.length > 0 && <span className="code"> {marks.map((n) => `[${n}]`).join(" ")}</span>}
      {!supported && <span className="badge badge-warn">Chưa kiểm chứng</span>}
    </li>
  );
}

function FeedbackBar({ answerId }: { answerId: string }) {
  const [comment, setComment] = useState("");
  const [state, send] = usePost<FeedbackResult>();
  const busy = state.kind === "busy";
  const rate = (rating: Rating) => {
    const note = comment.trim();
    void send("/assistant/feedback", {
      answer_id: answerId,
      rating,
      comment: note === "" ? null : note,
    });
  };
  return (
    <div className="insight-block">
      <h4>Phản hồi về câu trả lời</h4>
      <div className="insight-form">
        <label>
          Ghi chú (không bắt buộc)
          <textarea
            rows={2}
            maxLength={COMMENT_MAX}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <div className="insight-actions">
          {(["up", "down"] as Rating[]).map((r) => (
            <button key={r} type="button" disabled={busy} onClick={() => rate(r)}>
              {ratingLabel(r)}
            </button>
          ))}
        </div>
      </div>
      {state.kind === "ok" && (
        <div className="alert form-saved" role="status">
          Đã ghi phản hồi
        </div>
      )}
      {state.kind === "error" && <PostError code={state.code} message={state.message} />}
    </div>
  );
}

function AnswerView({ answer }: { answer: Answer }) {
  if (answer.status === "insufficient_evidence") {
    return (
      <>
        <EmptyState
          title={answerStatusLabel(answer.status)}
          hint="Dữ liệu của case này chưa đủ để trả lời câu hỏi."
        />
        <FeedbackBar key={answer.answer_id} answerId={answer.answer_id} />
      </>
    );
  }
  return (
    <>
      <ul className="answer-list">
        {answer.sentences.map((s, i) => (
          <SentenceItem key={i} text={s.text} supported={s.supported} marks={s.citations} />
        ))}
      </ul>
      <p className="insight-footer">
        {answer.validation.supported} / {answer.validation.sentences} câu đã kiểm chứng. Mô hình{" "}
        <span className="code">{answer.model}</span>.
      </p>
      <CitationList citations={answer.citations} />
      <FeedbackBar key={answer.answer_id} answerId={answer.answer_id} />
    </>
  );
}

function AskBox({ caseId }: { caseId: string }) {
  const [question, setQuestion] = useState("");
  const [state, ask] = usePost<Answer>();
  const busy = state.kind === "busy";
  return (
    <div>
      <form
        className="insight-form"
        onSubmit={(e) => {
          e.preventDefault();
          void ask("/assistant/chat", { case_id: caseId, question: question.trim(), language: "vi" });
        }}
      >
        <label>
          Câu hỏi về case này
          <textarea
            rows={2}
            maxLength={QUESTION_MAX}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <div className="insight-actions">
          <button type="submit" className="btn-primary" disabled={busy || question.trim() === ""}>
            Hỏi
          </button>
        </div>
      </form>
      {busy && (
        <p role="status" className="muted">
          Đang hỏi trợ lý…
        </p>
      )}
      {state.kind === "error" && <PostError code={state.code} message={state.message} />}
      {state.kind === "ok" && <AnswerView answer={state.envelope.data} />}
    </div>
  );
}

function NarrativeBox({ caseId }: { caseId: string }) {
  const [state, draft] = usePost<DraftNarrative>();
  const busy = state.kind === "busy";
  return (
    <div className="insight-block">
      <h4>Bản nháp báo cáo</h4>
      <div className="insight-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => void draft(`/cases/${encodeURIComponent(caseId)}/narrative`, { language: "vi" })}
        >
          Soạn bản nháp
        </button>
      </div>
      {busy && (
        <p role="status" className="muted">
          Đang soạn bản nháp…
        </p>
      )}
      {state.kind === "error" && <PostError code={state.code} message={state.message} />}
      {state.kind === "ok" && (
        <>
          <div className="alert alert-warning" role="note">
            <div>
              <strong className="alert-title">DRAFT — requires investigator review</strong>
              Bản nháp — cần investigator xem lại
            </div>
          </div>
          {state.envelope.meta.knowledge === "unavailable" && (
            <p className="muted">Không tra được tài liệu tham chiếu</p>
          )}
          <Markdown text={state.envelope.data.narrative.markdown} />
          <CitationList citations={state.envelope.data.citations} />
        </>
      )}
    </div>
  );
}

function TypologyBlock({ match }: { match: TypologyMatch }) {
  const { setHighlight } = useCaseHighlight();
  const nodeIds = Array.from(new Set(match.citations.flatMap((c) => c.node_ids)));
  return (
    <div className="insight-block">
      <h4>
        {typologyLabel(match.typology)}
        <code className="cell-sub">{match.typology}</code>
      </h4>
      <p>
        {match.rule_ids.map((id) => (
          <RuleLabel key={id} id={id} />
        ))}
      </p>
      <p className="free-text">{match.definition}</p>
      {match.transactions.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Giao dịch</th>
                <th>Thời điểm</th>
                <th>Từ tài khoản</th>
                <th>Đến tài khoản</th>
                <th className="num">Số tiền (VND)</th>
                <th>Kênh</th>
              </tr>
            </thead>
            <tbody>
              {match.transactions.map((t) => (
                <tr key={t.txn_id}>
                  <td className="code">{t.txn_id}</td>
                  <td>{formatDateTime(t.txn_ts)}</td>
                  <td className="code">{dash(t.from_account_id)}</td>
                  <td className="code">{dash(t.to_account_id)}</td>
                  <td className="num">{formatVnd(t.amount_vnd)}</td>
                  <td>{channelLabel(t.channel)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {match.chunks.map((c) => (
        <div key={c.chunk_id} className="citation-detail">
          <span className="code">{c.chunk_id}</span>
          {c.title !== null && ` ${c.title}`}
          {c.excerpt !== null && <p className="free-text">{c.excerpt}</p>}
        </div>
      ))}
      <div className="insight-actions">
        <button type="button" disabled={nodeIds.length === 0} onClick={() => setHighlight(nodeIds)}>
          Highlight
        </button>
      </div>
    </div>
  );
}

function TypologyPanel({ caseId }: { caseId: string }) {
  return (
    <ApiPanel<Typologies> path={`/cases/${encodeURIComponent(caseId)}/typologies`}>
      {(data, meta) => (
        <>
          <h4>Kiểu hành vi khớp</h4>
          {meta.knowledge === "unavailable" && <p className="muted">Không tra được tài liệu tham chiếu</p>}
          {data.typologies.length === 0 ? (
            <EmptyState title="Chưa có kiểu hành vi nào khớp với cảnh báo của case này" />
          ) : (
            data.typologies.map((m) => <TypologyBlock key={m.typology} match={m} />)
          )}
        </>
      )}
    </ApiPanel>
  );
}

/**
 * Question and answer, draft narrative and typology explainer. The assistant only explains: it has
 * no button that changes a case, and it never fills the decision form.
 */
export default function AssistantPanel({ caseId }: { caseId: string }) {
  const { clearHighlight } = useCaseHighlight();
  return (
    <div>
      <AskBox caseId={caseId} />
      <div className="insight-actions">
        <button type="button" onClick={clearHighlight}>
          Bỏ highlight
        </button>
      </div>
      <NarrativeBox caseId={caseId} />
      <TypologyPanel caseId={caseId} />
    </div>
  );
}
