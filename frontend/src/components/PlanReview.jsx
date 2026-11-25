import { useState } from "react";

export default function PlanReview({ payload, onApprove, disabled }) {
  const [items, setItems] = useState(payload.sub_questions ?? []);
  const update = (i, v) => setItems(items.map((x, j) => (j === i ? v : x)));
  const remove = (i) => setItems(items.filter((_, j) => j !== i));
  const valid = items.map((s) => s.trim()).filter(Boolean);

  return (
    <section className="review">
      <div className="review-head">검색 계획 확인</div>
      <p className="review-msg">{payload.message}</p>
      <ol>
        {items.map((s, i) => {
          const original = payload.sub_questions?.indexOf(s);
          const query = original >= 0 ? payload.queries?.[original] : null;
          return (
            <li key={i}>
              <div className="review-row">
                <input value={s} onChange={(e) => update(i, e.target.value)} placeholder="하위 질문" />
                <button className="icon-btn" onClick={() => remove(i)} title="삭제">✕</button>
              </div>
              <div className="review-q">{query ? `검색어: ${query}` : "새 하위 질문은 문장 그대로 검색해요"}</div>
            </li>
          );
        })}
      </ol>
      <div className="review-actions">
        <button className="ghost" onClick={() => setItems([...items, ""])} disabled={items.length >= 6}>
          + 하위 질문 추가
        </button>
        <button className="send" disabled={disabled || !valid.length} onClick={() => onApprove(valid)}>
          이대로 검색 시작
        </button>
      </div>
    </section>
  );
}
