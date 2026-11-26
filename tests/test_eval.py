"""품질 평가 지표와 평가 스크립트 테스트"""
import json

import pytest

import research_agent.nodes as n
from eval import evaluators as ev
from eval import run_eval

from conftest import StructuredStub

SOURCES = [{"n": 1, "url": "https://a.com/x"}, {"n": 2, "url": "https://www.b.com/y"}, {"n": 3, "url": "https://a.com/z"}]


def test_citation_validity():
    assert ev.citation_validity({"report": "가 [1] 나 [2]", "sources": SOURCES})["score"] == 1.0
    r = ev.citation_validity({"report": "가 [1] 나 [9]", "sources": SOURCES})
    assert r["score"] == 0.5 and "9" in r["comment"]
    assert ev.citation_validity({"report": "인용 없음", "sources": SOURCES})["score"] == 0.0


def test_citation_coverage_ignores_headings_and_short_lines():
    report = "# 제목\n\n짧은 줄\n이 문장은 근거가 붙은 충분히 긴 주장입니다 [1]\n이 문장은 근거가 없는 충분히 긴 주장입니다 그렇죠\n| --- | --- |"
    assert ev.citation_coverage({"report": report})["score"] == 0.5


def test_subq_coverage_and_diversity():
    assert ev.subq_coverage({"covered": [True, False, True, True]})["score"] == 0.75
    assert ev.source_diversity({"sources": SOURCES}, target=4)["score"] == 0.5  # a.com, b.com


def test_efficiency_returns_multiple_results():
    res = ev.efficiency({"num_searches": 5, "loop_count": 2, "latency_sec": 12.34, "revised_sentences": 1})["results"]
    assert {r["key"]: r["score"] for r in res} == {"num_searches": 5, "num_rounds": 2, "latency_sec": 12.3, "revised_sentences": 1}


def test_numeric_grounding():
    ev_ = [{"n": 1, "content": "회사 매출 1,200억 원"}]
    out = {"report": "# 제목\n회사 매출은 1200억 원이다 [1]. 회사 이익은 300억 원이다 [1].\n설명만 있는 문장이다.", "evidence": ev_}
    r = ev.numeric_grounding(out)
    assert r["score"] == 0.5 and "1/2" in r["comment"] and "300억 원" in r["comment"]
    assert ev.numeric_grounding({"report": "수치 없는 보고서", "evidence": []})["score"] == 1.0


REPORT = "# 보고서\n국내 AI 스타트업 투자액은 2,450억 원이다 [1]. 트웰브랩스는 700억 원을 유치했다 [2].\n요약 문장입니다."
EVID = [{"n": 1, "title": "t1", "content": "투자액 2,450억 원"}, {"n": 2, "title": "t2", "content": "트웰브랩스 700억 원 유치"}]


def judge_stub(seen):
    def h(name, prompt):
        seen.append((name, prompt))
        if name == "AspectJudgement":
            return ev.AspectJudgement(covered=[True, False], reason="두 번째 빠짐")
        if name == "ClaimExtraction":
            return ev.ClaimExtraction(claims=[
                ev.ExtractedClaim(quote="국내 AI 스타트업 투자액은 2,450억 원이다 [1].", cited=[1]),
                ev.ExtractedClaim(quote="1분기 반도체 수출액은 785억 달러다.", cited=[]),  # 보고서에 없음 (근거 자료 문장)
                ev.ExtractedClaim(quote="트웰브랩스는 700억 원을 유치했다", cited=[2]),  # 마침표·번호 빠져도 같은 문장
            ])
        if name == "ClaimVerdicts":
            return ev.ClaimVerdicts(verdicts=["Supported ", "partial"], reasons=["a", "b"])
        raise AssertionError(name)
    return StructuredStub(h)


def test_llm_judges_with_stub():
    seen = []
    aspect, grounded = ev.make_llm_judges(judge_stub(seen))
    assert aspect({"question": "Q"}, {"report": "r"}, {"aspects": ["x", "y"]})["score"] == 0.5
    g = grounded({"report": REPORT, "evidence": EVID})
    assert g["score"] == 0.75  # (1 + 0.5) / 2, 보고서에 없는 주장은 제외
    assert "심판 오류로 제외 1건" in g["comment"] and "(partial) 트웰브랩스" in g["comment"]
    extract_prompt = next(p for n_, p in seen if n_ == "ClaimExtraction")
    verify_prompt = next(p for n_, p in seen if n_ == "ClaimVerdicts")
    assert "투자액 2,450억 원" not in extract_prompt  # 1단계에는 근거 자료를 보여 주지 않음
    assert "785억" not in verify_prompt  # 제외된 주장은 판정하지 않음
    assert grounded({"report": "", "evidence": []})["score"] == 0.0


@pytest.mark.parametrize(
    "quote,ok",
    [
        ("국내 AI 스타트업 투자액은 2,450억 원이다 [1].", True),
        ("국내 AI 스타트업 투자액은 2450억 원이었다", True),  # 어미·쉼표 차이
        ("국내 AI 스타트업 투자액은 3,000억 원이다", False),  # 문장은 비슷하지만 수치가 보고서에 없음
        ("1분기 반도체 수출액은 785억 달러다.", False),
        ("", False),
    ],
)
def test_claim_in_report(quote, ok):
    assert ev.claim_in_report(quote, REPORT) is ok


def test_rejudge_tool(tmp_path):
    from eval import rejudge

    rows = [
        {"variant": "v", "id": "ai-regulation", "rep": 1, "question": "Q", "error": None, "report": REPORT, "evidence": EVID,
         "scores": {"groundedness": 0.4, "aspect_coverage": 1.0}, "comments": {}},
        {"variant": "v", "id": "ai-regulation", "rep": 2, "question": "Q", "error": "boom", "scores": {}, "comments": {}},
    ]
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"meta": {"time": "t", "n_examples": 1, "judge": "gpt-4o", "mode": "로컬"}, "rows": rows}, ensure_ascii=False), encoding="utf-8")
    out = rejudge.main([str(f)], judge=judge_stub([]))
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    r = data["rows"][0]
    assert r["scores"]["groundedness"] == 0.75 and r["scores"]["groundedness_old"] == 0.4
    assert r["scores"]["aspect_coverage"] == 1.0  # --aspect 없으면 그대로
    assert "재채점 전후" in out.read_text(encoding="utf-8")
    assert data["summary_before"]["v"]["groundedness"] == 0.4


def test_call_evaluator_matches_langsmith_arg_rules():
    seen = {}

    def needs_all(inputs, outputs, reference_outputs):
        seen.update(inputs=inputs, ref=reference_outputs)
        return {"key": "k", "score": 1}

    assert run_eval.call_evaluator(needs_all, {"question": "Q"}, {}, {"aspects": ["a"]}) == [{"key": "k", "score": 1}]
    assert seen == {"inputs": {"question": "Q"}, "ref": {"aspects": ["a"]}}


def test_dataset_is_well_formed():
    data = run_eval.load_dataset()
    assert len(data) == 10 and len({d["id"] for d in data}) == 10
    assert all(d["question"] and 3 <= len(d["aspects"]) <= 5 for d in data)


def test_run_eval_end_to_end_with_stubs(stubs, tmp_path, monkeypatch):
    """가짜 모델로 평가 스크립트 전체(실행 → 채점 → 보고서 저장)를 돌려 본다"""
    # 재검색 결과("retry")가 들어오기 전까지는 마지막 하위 질문을 부족으로 판정
    def h(name, prompt):
        if name == "Evaluation":
            return n.Evaluation(covered=[True, True, "retry" in prompt], missing_info="")
        return stubs["llm"].handler(name, prompt)

    judge = StructuredStub(h)
    monkeypatch.setattr(n, "eval_llm", judge)
    monkeypatch.setattr(n, "_chat", lambda model: judge)
    md = run_eval.main(["--limit", "2", "--no-judge", "--variants", "no_plan", "baseline", "improved", "--concurrency", "1", "--out", str(tmp_path)])
    text = md.read_text(encoding="utf-8")
    assert "## 요약 (평균)" in text and "baseline" in text and "improved" in text
    data = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    s = data["summary"]
    assert s["baseline"]["n"] == 2 and s["improved"]["n"] == 2
    # baseline은 재검색이 없고, improved는 부족한 항목을 재검색한다
    assert s["baseline"]["num_rounds"] == 1 and s["improved"]["num_rounds"] > 1
    assert s["improved"]["num_searches"] > s["baseline"]["num_searches"]
    assert s["no_plan"]["num_searches"] == 1  # 질문 분해 없이 한 번만 검색


def test_repeat_gives_mean_and_sd(stubs, tmp_path):
    md = run_eval.main(["--limit", "1", "--no-judge", "--variants", "baseline", "--repeat", "3", "--concurrency", "1", "--out", str(tmp_path)])
    data = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["summary"]["baseline"]["reps"] == 3 and data["summary"]["baseline"]["n"] == 3
    assert data["summary"]["baseline"]["num_searches_sd"] == 0.0  # 가짜 모델이라 회차 간 차이 없음
    text = md.read_text(encoding="utf-8")
    assert "± 0.00" in text and "반복: 3회" in text


def test_summarize_sd():
    rows = [
        {"variant": "v", "rep": 1, "error": None, "scores": {"aspect_coverage": 0.8}},
        {"variant": "v", "rep": 2, "error": None, "scores": {"aspect_coverage": 1.0}},
        {"variant": "v", "rep": 2, "error": "boom", "scores": {}},
    ]
    s = run_eval.summarize(rows, ["v"])["v"]
    assert s["aspect_coverage"] == 0.9 and s["aspect_coverage_sd"] == 0.141 and s["errors"] == 1


def test_check_numbers_tool(tmp_path, capsys):
    from eval import check_numbers

    rows = [{"variant": "v", "id": "q", "rep": 1, "error": None,
             "report": "회사 매출은 1200억 원이다 [1]. 회사 이익은 300억 원이다 [1].",
             "evidence": [{"n": 1, "content": "회사 매출 1,200억 원"}]}]
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    check_numbers.main([str(f)])
    out = capsys.readouterr().out
    assert "300억 원: 근거 자료에 없는 값" in out and "2개 중 1개 걸림" in out


def test_run_eval_saves_evidence(stubs, tmp_path):
    md = run_eval.main(["--limit", "1", "--no-judge", "--variants", "improved", "--concurrency", "1", "--out", str(tmp_path)])
    row = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))["rows"][0]
    assert row["evidence"] and {"n", "content"} <= set(row["evidence"][0])
