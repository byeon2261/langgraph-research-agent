import { useState } from "react";

export default function Composer({ onSubmit, onStop, running, compact }) {
  const [text, setText] = useState("");

  const submit = () => {
    const q = text.trim();
    if (!q || running) return;
    onSubmit(q);
    setText("");
  };

  return (
    <div className={`composer ${compact ? "compact" : ""}`}>
      <textarea
        value={text}
        placeholder="무엇을 조사할까요? 예) 2026년 국내 생성형 AI 스타트업 투자 동향"
        rows={compact ? 1 : 3}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
      />
      {running ? (
        <button className="send stop" onClick={onStop}>중지</button>
      ) : (
        <button className="send" onClick={submit} disabled={!text.trim()}>
          리서치 시작
        </button>
      )}
    </div>
  );
}
