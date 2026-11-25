function hostname(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// final=true면 보고서의 [번호]와 같은 번호(s.n)를 쓴다
export default function SourcesPanel({ sources, final }) {
  return (
    <aside className="sources">
      <div className="sources-head">
        출처 {sources.length}개{!final && sources.length > 0 && <span className="muted"> · 수집 중</span>}
      </div>
      {sources.length === 0 && <div className="sources-empty">검색 결과가 여기에 표시돼요</div>}
      <ol>
        {sources.map((s, i) => (
          <li key={s.url + i} id={final ? `src-${s.n}` : undefined}>
            <a href={s.url} target="_blank" rel="noreferrer">
              <span className={`src-num ${final ? "" : "pending"}`}>{final ? s.n : "·"}</span>
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
