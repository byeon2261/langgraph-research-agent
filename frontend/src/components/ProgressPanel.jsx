const LABELS = {
  generate_query: "검색어 생성",
  search: "웹 검색",
  evaluate: "충분성 평가",
  write_report: "보고서 작성",
};

function StepIcon({ status }) {
  if (status === "running") return <span className="spinner" />;
  if (status === "done") return <span className="icon done">✓</span>;
  if (status === "retry") return <span className="icon retry">↻</span>;
  return <span className="icon">•</span>;
}

export default function ProgressPanel({ steps, running, open, onToggle }) {
  const loops = steps.filter((s) => s.node === "generate_query").length;
  return (
    <section className="progress">
      <button className="progress-head" onClick={onToggle}>
        <span>
          {running ? "리서치 진행 중…" : "리서치 과정"} · 검색 {loops}회
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
