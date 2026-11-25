function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export default function SourcesPanel({ sources }) {
  return (
    <aside className="sources">
      <div className="sources-head">출처 {sources.length}개</div>
      {sources.length === 0 && <div className="sources-empty">검색 결과가 여기에 표시돼요</div>}
      <ol>
        {sources.map((s, i) => (
          <li key={s.url + i}>
            <a href={s.url} target="_blank" rel="noreferrer">
              <span className="src-num">{i + 1}</span>
              <span className="src-text">
                <span className="src-title">{s.title || hostname(s.url)}</span>
                <span className="src-host">{hostname(s.url)}</span>
              </span>
            </a>
          </li>
        ))}
      </ol>
    </aside>
  );
}
