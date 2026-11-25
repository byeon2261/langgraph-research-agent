import { describe as suite, expect, it } from "vitest";
import { applyUpdate, describe, linkCitations, newTurn } from "./turns.js";

const SOURCES = [
  { n: 1, url: "https://a.com" },
  { n: 2, url: "https://b.com" },
];

suite("linkCitations", () => {
  it("[번호]를 같은 번호의 출처 링크로 바꾼다", () => {
    expect(linkCitations("가 [1] 나 [2]", SOURCES)).toBe("가 [[1]](https://a.com) 나 [[2]](https://b.com)");
  });
  it("없는 번호와 이미 링크인 것은 그대로 둔다", () => {
    expect(linkCitations("[9] [1](x)", SOURCES)).toBe("[9] [1](x)");
  });
  it("출처가 없으면 원문 그대로", () => {
    expect(linkCitations("가 [1]", [])).toBe("가 [1]");
  });
});

suite("applyUpdate", () => {
  it("plan/review_plan이 하위 질문을 기록한다", () => {
    let t = applyUpdate(newTurn("Q"), "plan", { sub_questions: ["A", "B"] });
    expect(t.subQuestions).toEqual(["A", "B"]);
    t = applyUpdate({ ...newTurn("Q"), ...t }, "review_plan", { sub_questions: ["A", "C"], pending_queries: [] });
    expect(t.subQuestions).toEqual(["A", "C"]);
  });

  it("검색 결과는 URL 중복 없이 모은다", () => {
    let t = newTurn("Q");
    t = { ...t, ...applyUpdate(t, "search", { results: [{ url: "u1" }, { url: "u2" }] }) };
    t = { ...t, ...applyUpdate(t, "search", { results: [{ url: "u2" }, { url: "u3" }] }) };
    expect(t.collected.map((x) => x.url)).toEqual(["u1", "u2", "u3"]);
  });

  it("검색 실패는 error, 평가 부족은 retry 상태", () => {
    const t = newTurn("Q");
    expect(applyUpdate(t, "search", { results: [], search_errors: ["x"] }).steps[0].status).toBe("error");
    expect(applyUpdate(t, "evaluate", { is_sufficient: false, covered: [] }).steps[0].status).toBe("retry");
    expect(applyUpdate(t, "evaluate", { is_sufficient: true, covered: [] }).steps[0].status).toBe("done");
  });

  it("write_report가 최종 보고서와 번호 붙은 출처를 넣고 스트리밍 초안을 지운다", () => {
    const t = { ...newTurn("Q"), draft: "쓰는 중" };
    const next = applyUpdate(t, "write_report", { report: "완성 [1]", sources: SOURCES });
    expect(next).toMatchObject({ report: "완성 [1]", sources: SOURCES, draft: "" });
  });
});

suite("describe", () => {
  it("평가 단계에 하위 질문별 ✓/✗와 규칙 메모를 보여 준다", () => {
    const text = describe("evaluate", { covered: [true, false], rule_notes: ["도메인 부족"], is_sufficient: false }, { subQuestions: ["A", "B"] });
    expect(text).toBe("✓ A\n✗ B\n! 도메인 부족\n→ 부족한 항목 재검색");
  });
  it("검색 실패 메시지", () => {
    expect(describe("search", { results: [], search_errors: ["'q': down"] })).toContain("검색 실패");
  });
});
