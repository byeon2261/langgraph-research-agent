import { useEffect, useState } from "react";

const LABELS = {
  plan: "리서치 계획",
  review_plan: "검색 계획 확정",
  generate_query: "추가 검색어 생성",
  search: "웹 검색",
  evaluate: "충분성 평가",
  write_report: "보고서 작성",
  verify_report: "수치 근거 확인",
};

function StepIcon({ status }) {
  if (status === "running") return <span className="spinner" />;
  if (status === "done") return <span className="icon done">✓</span>;
  if (status === "retry") return <span className="icon retry">↻</span>;
  if (status === "error") return <span className="icon err">!</span>;
  return <span className="icon">•</span>;
}

export default function ProgressPanel({ steps, running, done }) {
  const [open, setOpen] = useState(!done);
  useEffect(() => {
    if (done) setOpen(false); // 보고서가 나오면 자동으로 접기
  }, [done]);

  const searches = steps.filter((s) => s.node === "search").length;
  const rounds = steps.filter((s) => s.node === "evaluate").length;
  return (
    <section className="progress">
      <button className="progress-head" onClick={() => setOpen((o) => !o)}>
        <span>
          {running ? "리서치 진행 중…" : "리서치 과정"} · 검색 {searches}건 · 평가 {rounds}회
        </span>
        <span className="chev">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={i} className={`step ${s.status}`}>
              <StepIcon status={s.status} />
              <div className="step-body">
                <div className="step-title">{LABELS[s.node] || s.node}</div>
                {s.detail && <div className="step-detail">{s.detail}</div>}
              </div>
            </li>
          ))}
          {running && (
            <li className="step running">
              <StepIcon status="running" />
              <div className="step-body">
                <div className="step-title">다음 단계 진행 중</div>
              </div>
            </li>
          )}
        </ol>
      )}
    </section>
  );
}
