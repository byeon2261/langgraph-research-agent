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
    ev_ = [{"n": 1, "content": "매출 1,200억 원"}]
    out = {"report": "# 제목\n매출은 1200억 원이다 [1]. 이익은 300억 원이다 [1].\n설명만 있는 문장이다.", "evidence": ev_}
    r = ev.numeric_grounding(out)
    assert r["score"] == 0.5 and "1/2" in r["comment"]
    assert ev.numeric_grounding({"report": "수치 없는 보고서", "evidence": []})["score"] == 1.0


def test_llm_judges_with_stub():
    def h(name, prompt):
        if name == "AspectJudgement":
            return ev.AspectJudgement(covered=[True, False], reason="두 번째 빠짐")
        return ev.GroundednessJudgement(claims=[
            ev.ClaimCheck(claim="a", cited=[1], verdict="supported"),
            ev.ClaimCheck(claim="b", cited=[1], verdict="partial"),
            ev.ClaimCheck(claim="c", cited=[], verdict="unsupported"),
            ev.ClaimCheck(claim="d", cited=[2], verdict="Supported "),
        ])

    aspect, grounded = ev.make_llm_judges(StructuredStub(h))
    a = aspect({"question": "Q"}, {"report": "r"}, {"aspects": ["x", "y"]})
    g = grounded({"report": "r", "evidence": [{"n": 1, "content": "c"}]})
    assert a["score"] == 0.5
    assert g["score"] == 0.625  # (1 + 0.5 + 0 + 1) / 4, 대소문자·공백 무시
    assert "(partial) b" in g["comment"] and "(unsupported) c" in g["comment"]
    assert grounded({"report": "", "evidence": []})["score"] == 0.0


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
