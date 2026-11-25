export default function Sidebar({ sessions, activeId, onSelect, onNew, onClear, disabled }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-dot" /> Research Agent
      </div>
      <button className="new-btn" onClick={onNew} disabled={disabled}>+ 새 리서치</button>
      <div className="history-label">최근 리서치</div>
      <ul className="history">
        {sessions.length === 0 && <li className="history-empty">아직 기록이 없어요</li>}
        {sessions.map((s) => (
          <li
            key={s.id}
            className={s.id === activeId ? "active" : ""}
            onClick={() => !disabled && onSelect(s.id)}
            title={s.title}
          >
            {s.title}
            {s.turns.length > 1 && <span className="turn-count"> +{s.turns.length - 1}</span>}
          </li>
        ))}
      </ul>
      {sessions.length > 0 && (
        <button className="clear-btn" onClick={onClear} disabled={disabled}>기록 모두 지우기</button>
      )}
    </aside>
  );
}
