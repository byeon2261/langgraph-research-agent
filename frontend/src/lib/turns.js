// 화면 상태(turn)를 다루는 순수 함수 모음 — React 없이 테스트할 수 있다

export const newTurn = (question) => ({
  question,
  steps: [],
  subQuestions: [],
  collected: [], // 검색 중 수집된 출처 (도착 순서)
  sources: [], // 보고서 [번호]와 같은 순서의 최종 출처
  draft: "", // 스트리밍 중인 보고서
  report: "",
  review: null, // interrupt payload
  error: "",
});

export function describe(node, values, turn) {
  if (node === "plan")
    return (values.sub_questions ?? []).map((q, i) => `${i + 1}. ${q}`).join("\n");
  if (node === "review_plan")
    return (values.pending_queries ?? []).map((t) => `${t.sub_question} → “${t.query}”`).join("\n");
  if (node === "generate_query")
    return (values.pending_queries ?? []).map((t) => `“${t.query}”`).join("\n");
  if (node === "search") {
    const r = values.results ?? [];
    const err = values.search_errors?.[0];
    return err ? `검색 실패: ${err}` : `“${r[0]?.query ?? ""}” → 결과 ${r.length}건`;
  }
  if (node === "evaluate") {
    const lines = (turn.subQuestions ?? []).map((q, i) => `${values.covered?.[i] ? "✓" : "✗"} ${q}`);
    (values.rule_notes ?? []).forEach((n) => lines.push(`! ${n}`));
    lines.push(values.is_sufficient ? "→ 충분함, 보고서 작성" : "→ 부족한 항목 재검색");
    return lines.join("\n");
  }
  if (node === "write_report") return "완료";
  if (node === "verify_report") {
    const k = values.revised_sentences ?? 0;
    const left = values.unverified_claims?.length ?? 0;
    if (!k) return "모든 수치가 근거 자료와 일치";
    return `근거에 없는 수치가 있는 문장 ${k}개 수정` + (left ? `\n! 여전히 확인 안 된 문장 ${left}개` : "");
  }
  return "";
}

export function applyUpdate(t, node, values) {
  let status = "done";
  if (node === "evaluate" && !values.is_sufficient) status = "retry";
  if (node === "search" && values.search_errors?.length) status = "error";
  if (node === "verify_report" && values.revised_sentences) status = "retry";
  const next = { steps: [...t.steps, { node, status, detail: describe(node, values, t) }] };
  if ((node === "plan" || node === "review_plan") && values.sub_questions)
    next.subQuestions = values.sub_questions;
  if (node === "search" && values.results) {
    const seen = new Set(t.collected.map((x) => x.url));
    next.collected = [...t.collected, ...values.results.filter((r) => r.url && !seen.has(r.url))];
  }
  if (node === "write_report") {
    next.report = values.report ?? "";
    next.sources = values.sources ?? [];
    next.draft = "";
  }
  // 수치 검사에서 고친 보고서가 오면 교체
  if (node === "verify_report" && values.report) next.report = values.report;
  return next;
}

// [1] 보고서의 [3] → 출처 3번 URL 링크 (번호가 백엔드 sources와 같다)
export function linkCitations(text, sources) {
  if (!sources?.length) return text;
  const byN = Object.fromEntries(sources.map((s) => [String(s.n), s.url]));
  return text.replace(/\[(\d+)\](?!\()/g, (m, d) => (byN[d] ? `[[${d}]](${byN[d]})` : m));
}
