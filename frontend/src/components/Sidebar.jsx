export default function Sidebar({ sessions, activeId, onSelect, onNew }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-dot" /> Research Agent
      </div>
      <button className="new-btn" onClick={onNew}>+ 새 리서치</button>
      <div className="history-label">최근 리서치</div>
      <ul className="history">
        {sessions.length === 0 && <li className="history-empty">아직 기록이 없어요</li>}
        {sessions.map((s) => (
          <li
            key={s.id}
            className={s.id === activeId ? "active" : ""}
            onClick={() => onSelect(s.id)}
            title={s.question}
          >
            {s.question}
          </li>
        ))}
      </ul>
    </aside>
  );
}
