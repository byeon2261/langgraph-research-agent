import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Sidebar from "./components/Sidebar.jsx";
import Composer from "./components/Composer.jsx";
import ProgressPanel from "./components/ProgressPanel.jsx";
import SourcesPanel from "./components/SourcesPanel.jsx";
import { runResearch } from "./api.js";

const EXAMPLES = [
  "LangGraph와 CrewAI의 최신 기능 차이와 도입 사례",
  "2026년 국내 생성형 AI 스타트업 투자 규모와 주요 투자사",
  "전기차 배터리 재활용 시장 전망과 주요 기업",
];

function describe(node, values) {
  if (node === "generate_query") return `“${values.queries?.at(-1) ?? ""}”`;
  if (node === "search") return `결과 ${values.results?.length ?? 0}건 수집`;
  if (node === "evaluate")
    return values.is_sufficient ? "충분함 → 보고서 작성" : `부족함: ${values.missing_info || "추가 검색 필요"}`;
  if (node === "write_report") return "완료";
  return "";
}

export default function App() {
  const [sessions, setSessions] = useState([]); // {id, question, steps, sources, report, error}
  const [activeId, setActiveId] = useState(null);
  const [running, setRunning] = useState(false);
  const [progressOpen, setProgressOpen] = useState(true);
  const abortRef = useRef(null);

  const active = sessions.find((s) => s.id === activeId);

  const patch = (id, fn) =>
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, ...fn(s) } : s)));

  const start = async (question) => {
    const id = crypto.randomUUID();
    setSessions((prev) => [{ id, question, steps: [], sources: [], report: "", error: "" }, ...prev]);
    setActiveId(id);
    setRunning(true);
    setProgressOpen(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await runResearch(
        question,
        (node, values) => {
          patch(id, (s) => {
            const status = node === "evaluate" && !values.is_sufficient ? "retry" : "done";
            const next = {
              steps: [...s.steps, { node, status, detail: describe(node, values) }],
            };
            if (node === "search" && values.results) {
              const seen = new Set(s.sources.map((x) => x.url));
              next.sources = [...s.sources, ...values.results.filter((r) => r.url && !seen.has(r.url))];
            }
            if (node === "write_report") next.report = values.report ?? "";
            return next;
          });
        },
        controller.signal
      );
      setProgressOpen(false);
    } catch (err) {
      if (err.name !== "AbortError") {
        patch(id, () => ({
          error: `${err.message}\nLangGraph 서버(.\\dev.ps1)가 켜져 있는지 확인하세요.`,
        }));
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();

  return (
    <div className="layout">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onSelect={(id) => !running && setActiveId(id)}
        onNew={() => !running && setActiveId(null)}
      />

      <main className="main">
        {!active ? (
          <div className="welcome">
            <h1>무엇을 조사해 드릴까요?</h1>
            <p>질문을 입력하면 검색 → 평가 → 재검색을 반복해 출처가 달린 보고서를 만들어요.</p>
            <Composer onSubmit={start} running={running} />
            <div className="examples">
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => start(e)} disabled={running}>{e}</button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="content">
              <div className="report-col">
                <h2 className="question">{active.question}</h2>
                <ProgressPanel
                  steps={active.steps}
                  running={running && active.id === activeId && !active.report}
                  open={progressOpen}
                  onToggle={() => setProgressOpen((o) => !o)}
                />
                {active.error && <pre className="error">{active.error}</pre>}
                {active.report ? (
                  <article className="report">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}
                    >
                      {active.report}
                    </ReactMarkdown>
                  </article>
                ) : (
                  !active.error && <div className="skeleton"><div /><div /><div /></div>
                )}
              </div>
              <SourcesPanel sources={active.sources} />
            </div>
            <div className="bottom">
              <Composer onSubmit={start} onStop={stop} running={running} compact />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
