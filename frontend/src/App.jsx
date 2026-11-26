import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Sidebar from "./components/Sidebar.jsx";
import Composer from "./components/Composer.jsx";
import ProgressPanel from "./components/ProgressPanel.jsx";
import SourcesPanel from "./components/SourcesPanel.jsx";
import PlanReview from "./components/PlanReview.jsx";
import { createThread, streamRun } from "./api.js";
import { applyUpdate, linkCitations, newTurn } from "./lib/turns.js";

const EXAMPLES = [
  "LangGraph와 CrewAI의 최신 기능 차이와 도입 사례",
  "2026년 국내 생성형 AI 스타트업 투자 규모와 주요 투자사",
  "전기차 배터리 재활용 시장 전망과 주요 기업",
];

const STORAGE_KEY = "research-agent:sessions";
const REVIEW_KEY = "research-agent:review";

// [5] 새로고침해도 기록이 남도록 브라우저에 저장 (실패해도 앱은 동작)
function load(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}
function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장 공간 부족 등은 무시 */
  }
}

export default function App() {
  const [sessions, setSessions] = useState(() => load(STORAGE_KEY, []));
  const [activeId, setActiveId] = useState(null);
  const [running, setRunning] = useState(false);
  const [review, setReview] = useState(() => load(REVIEW_KEY, true));
  const abortRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => save(STORAGE_KEY, sessions.slice(0, 30)), [sessions]);
  useEffect(() => save(REVIEW_KEY, review), [review]);

  const active = sessions.find((s) => s.id === activeId);
  const lastTurn = active?.turns.at(-1);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active?.turns.length, lastTurn?.review]);

  const patchSession = (sid, fn) =>
    setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, ...fn(s) } : s)));
  const patchTurn = (sid, ti, fn) =>
    patchSession(sid, (s) => ({
      turns: s.turns.map((t, i) => (i === ti ? { ...t, ...fn(t) } : t)),
    }));

  async function execute(sid, ti, threadId, args) {
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamRun(
        threadId,
        args,
        {
          onUpdate: (node, values) => patchTurn(sid, ti, (t) => applyUpdate(t, node, values)),
          onToken: (tok) => patchTurn(sid, ti, (t) => ({ draft: t.draft + tok })), // [7]
          onInterrupt: (payload) => patchTurn(sid, ti, () => ({ review: payload })), // [6]
        },
        controller.signal
      );
    } catch (err) {
      patchTurn(sid, ti, () => ({
        error:
          err.name === "AbortError"
            ? "중지했어요."
            : `${err.message}\nLangGraph 서버(.\\dev.ps1)가 켜져 있는지 확인하세요. 서버를 다시 켰다면 '새 리서치'로 시작해 주세요.`,
      }));
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  async function ask(question) {
    // 활성 세션이 있으면 같은 thread에서 후속 질문 (서버가 이전 대화를 기억)
    let sid = active?.id;
    let threadId = active?.threadId;
    let ti;
    try {
      if (!threadId) threadId = await createThread();
    } catch (err) {
      threadId = null;
    }
    if (active) {
      ti = active.turns.length;
      patchSession(sid, (s) => ({ threadId, turns: [...s.turns, newTurn(question)] }));
    } else {
      sid = crypto.randomUUID();
      ti = 0;
      setSessions((prev) => [{ id: sid, threadId, title: question, turns: [newTurn(question)] }, ...prev]);
      setActiveId(sid);
    }
    if (!threadId) {
      patchTurn(sid, ti, () => ({ error: "서버에 연결하지 못했어요. LangGraph 서버(.\\dev.ps1)가 켜져 있는지 확인하세요." }));
      return;
    }
    await execute(sid, ti, threadId, { input: { question, review, loop_count: 0 } });
  }

  function approve(subs) {
    const ti = active.turns.length - 1;
    patchTurn(active.id, ti, () => ({ review: null }));
    execute(active.id, ti, active.threadId, { resume: { sub_questions: subs } });
  }

  const stop = () => abortRef.current?.abort();

  const reviewToggle = (
    <label className="toggle">
      <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} disabled={running} />
      검색 전 계획 확인
    </label>
  );

  return (
    <div className="layout">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        disabled={running}
        onSelect={setActiveId}
        onNew={() => setActiveId(null)}
        onClear={() => {
          if (confirm("리서치 기록을 모두 지울까요?")) {
            setSessions([]);
            setActiveId(null);
          }
        }}
      />

      <main className="main">
        {!active ? (
          <div className="welcome">
            <h1>무엇을 조사해 드릴까요?</h1>
            <p>질문을 하위 질문으로 나눠 검색하고, 근거가 부족하면 다시 찾아 출처가 달린 보고서를 만들어요.</p>
            <Composer onSubmit={ask} running={running} />
            <div className="welcome-opts">{reviewToggle}</div>
            <div className="examples">
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => ask(e)} disabled={running}>{e}</button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <div className="content">
              {/* 보고서 열과 입력창을 한 열로 묶어 입력창이 보고서와 같은 너비가 되게 한다 */}
              <div className="main-col">
              <div className="report-col">
                {active.turns.map((t, i) => {
                  const isLast = i === active.turns.length - 1;
                  // 보고서가 나온 뒤에도 수치 검사(verify_report)가 끝날 때까지는 진행 중으로 표시
                  const busy = running && isLast && !t.review;
                  const text = t.report || t.draft;
                  return (
                    <section className="turn" key={i}>
                      <h2 className="question">
                        {i > 0 && <span className="followup-tag">후속 질문</span>}
                        {t.question}
                      </h2>
                      <ProgressPanel steps={t.steps} running={busy} done={!!t.report && !busy} />
                      {t.review && isLast && (
                        <PlanReview payload={t.review} disabled={running} onApprove={approve} />
                      )}
                      {t.error && <pre className="error">{t.error}</pre>}
                      {text ? (
                        <article className={`report ${t.report ? "" : "streaming"}`}>
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}
                          >
                            {linkCitations(text, t.sources)}
                          </ReactMarkdown>
                        </article>
                      ) : (
                        busy && <div className="skeleton"><div /><div /><div /></div>
                      )}
                    </section>
                  );
                })}
                <div ref={endRef} />
              </div>
              <div className="bottom">
                <Composer
                  onSubmit={ask}
                  onStop={stop}
                  running={running}
                  compact
                  placeholder="이어서 질문하기 (예: 그중 EU 규제를 더 자세히)"
                />
                <div className="bottom-opts">{reviewToggle}</div>
              </div>
              </div>
              <SourcesPanel
                sources={lastTurn?.sources.length ? lastTurn.sources : lastTurn?.collected ?? []}
                final={!!lastTurn?.sources.length}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
