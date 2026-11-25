"""노드와 유틸 함수 단위 테스트"""
import re

import pytest

import research_agent.nodes as n
from research_agent.graph import fan_out, route_after_evaluate

from conftest import FAST


def r(url, sub, title="t"):
    return {"url": url, "sub_question": sub, "title": title, "content": "c"}


# ---------- 설정 ----------
def test_settings_override_by_configurable():
    s = n.get_settings({"configurable": {"max_loops": 1, "eval_model": "x", "unknown": 9}})
    assert s.max_loops == 1 and s.eval_model == "x"
    assert n.get_settings(None) == n.DEFAULTS


def test_plan_without_decomposition(stubs):
    out = n.plan({"question": "원래 질문"}, {"configurable": {"use_plan": False}})
    assert out["sub_questions"] == ["원래 질문"]
    assert out["pending_queries"] == [{"query": "원래 질문", "sub_question": "원래 질문", "round": 1, "turn": 1}]
    assert stubs["llm"].prompts == []  # LLM 호출 없음


def test_today_format():
    assert re.fullmatch(r"\d{4}년 \d{2}월 \d{2}일", n._today())


# ---------- _select: 출처 번호의 기준 ----------
def test_select_orders_by_subquestion_and_dedupes():
    state = {
        "sub_questions": ["A", "B"],
        "results": [r("u-b1", "B"), r("u-a1", "A"), r("u-a1", "A"), r("u-a2", "A"), r("u-old", "OLD")],
    }
    picked = n._select(state)
    assert [x["url"] for x in picked] == ["u-a1", "u-a2", "u-b1"]  # A 먼저, 중복 제거, 이전 하위 질문 제외


def test_select_caps_per_subquestion():
    state = {"sub_questions": ["A"], "results": [r(f"u{i}", "A") for i in range(10)]}
    s = n.get_settings({"configurable": {"max_results_per_subq_in_prompt": 3}})
    assert len(n._select(state, s)) == 3


def test_select_is_deterministic_regardless_of_arrival_order():
    rs = [r("a1", "A"), r("b1", "B"), r("a2", "A")]
    s1 = n._select({"sub_questions": ["A", "B"], "results": rs})
    s2 = n._select({"sub_questions": ["A", "B"], "results": [rs[1], rs[2], rs[0]]})
    assert [x["sub_question"] for x in s1] == [x["sub_question"] for x in s2] == ["A", "A", "B"]


def rr(url, sub, rnd, turn=1):
    return {**r(url, sub), "round": rnd, "turn": turn}


def test_select_keeps_retry_results_when_capped():
    """회귀 테스트 (2026-11-25 평가에서 발견):
    첫 검색 결과가 상한을 채우면 재검색 결과가 프롬프트에서 빠지던 버그"""
    results = [rr(f"r1-{i}", "A", 1) for i in range(3)] + [rr(f"r2-{i}", "A", 2) for i in range(3)] + [rr(f"r3-{i}", "A", 3) for i in range(3)]
    s = n.get_settings({"configurable": {"max_results_per_subq_in_prompt": 6}})
    picked = [x["url"] for x in n._select({"sub_questions": ["A"], "current_turn": 1, "results": results}, s)]
    assert picked == ["r2-0", "r2-1", "r2-2", "r3-0", "r3-1", "r3-2"]  # 최근 두 라운드, 라운드 순서로 정렬


def test_select_ignores_previous_turn():
    results = [rr("old", "A", 1, turn=1), rr("new", "A", 1, turn=2)]
    picked = n._select({"sub_questions": ["A"], "current_turn": 2, "results": results})
    assert [x["url"] for x in picked] == ["new"]


# ---------- evaluate: 규칙 점검 ----------
def test_evaluate_rules_override_lenient_llm(stubs, monkeypatch):
    always_ok = lambda name, p: n.Evaluation(covered=[True, True], missing_info="")
    monkeypatch.setattr(n, "eval_llm", __import__("conftest").StructuredStub(always_ok))
    state = {"question": "Q", "sub_questions": ["A", "B"], "results": [r("https://same.com/1", "A")]}
    out = n.evaluate(state, {})
    assert out["is_sufficient"] is False
    assert out["covered"] == [False, False]  # 결과 수 부족 → LLM이 true여도 false
    assert any("도메인" in x for x in out["rule_notes"])
    assert "규칙 점검" in out["missing_info"]


def test_evaluate_passes_when_rules_relaxed(stubs, monkeypatch):
    always_ok = lambda name, p: n.Evaluation(covered=[True], missing_info="")
    monkeypatch.setattr(n, "eval_llm", __import__("conftest").StructuredStub(always_ok))
    state = {"question": "Q", "sub_questions": ["A"], "results": [r("https://a.com", "A")]}
    cfg = {"configurable": {"min_domains": 0, "min_results_per_subq": 0}}
    assert n.evaluate(state, cfg)["is_sufficient"] is True


def test_evaluate_pads_short_covered_list(stubs, monkeypatch):
    short = lambda name, p: n.Evaluation(covered=[True], missing_info="x")
    monkeypatch.setattr(n, "eval_llm", __import__("conftest").StructuredStub(short))
    state = {"question": "Q", "sub_questions": ["A", "B", "C"], "results": []}
    assert n.evaluate(state, {"configurable": {"min_domains": 0, "min_results_per_subq": 0}})["covered"] == [True, False, False]


def test_prompts_include_today(stubs):
    n.plan({"question": "최신 동향"}, {})
    assert n._today() in stubs["llm"].prompts[-1]


# ---------- generate_query: 번호로 하위 질문 연결 ----------
@pytest.mark.parametrize("no,expected", [(1, "B"), (2, "C"), (99, "C"), (0, "B")])
def test_generate_query_maps_by_number(stubs, monkeypatch, no, expected):
    h = lambda name, p: n.FollowUp(items=[n.FollowUpItem(sub_question_no=no, query="new")])
    monkeypatch.setattr(n, "llm", __import__("conftest").StructuredStub(h))
    state = {"question": "Q", "sub_questions": ["A", "B", "C"], "covered": [True, False, False], "loop_count": 1, "current_turn": 1}
    out = n.generate_query(state, {})
    assert out["pending_queries"] == [{"query": "new", "sub_question": expected, "round": 2, "turn": 1}]
    assert out["loop_count"] == 2


# ---------- review_plan: interrupt 응답 처리 ----------
TASKS = [{"sub_question": "A", "query": "qa"}, {"sub_question": "B", "query": "qb"}]


def test_review_plan_skips_when_review_off(monkeypatch):
    monkeypatch.setattr(n, "interrupt", lambda p: pytest.fail("interrupt 호출되면 안 됨"))
    out = n.review_plan({"pending_queries": TASKS, "review": False})
    assert out["queries"] == ["qa", "qb"]


@pytest.mark.parametrize(
    "answer,subs,queries",
    [
        (True, ["A", "B"], ["qa", "qb"]),  # 그대로 승인
        ({"sub_questions": ["B", " 새 질문 ", ""]}, ["B", "새 질문"], ["qb", "새 질문"]),  # 삭제·추가·빈칸 제거
    ],
)
def test_review_plan_applies_answer(monkeypatch, answer, subs, queries):
    monkeypatch.setattr(n, "interrupt", lambda p: answer)
    out = n.review_plan({"pending_queries": TASKS, "review": True})
    assert out["sub_questions"] == subs and out["queries"] == queries


# ---------- search ----------
def test_search_truncates_and_tags(stubs):
    out = n.search({"query": "q", "sub_question": "A"}, {"configurable": {"max_content_chars": 10}})
    assert all(len(x["content"]) == 10 and x["sub_question"] == "A" for x in out["results"])


def test_search_retries_then_records_error(stubs):
    stubs["search"].fail_on = {"q"}
    out = n.search({"query": "q", "sub_question": "A"}, {"configurable": {"search_retries": 2}})
    assert out["results"] == [] and "tavily down" in out["search_errors"][0]
    assert stubs["search"].calls == ["q", "q", "q"]  # 1회 + 재시도 2회


# ---------- 라우팅 ----------
@pytest.mark.parametrize(
    "state,expected",
    [
        ({"is_sufficient": True, "loop_count": 1, "max_loops": 3}, "write_report"),
        ({"is_sufficient": False, "loop_count": 1, "max_loops": 3}, "generate_query"),
        ({"is_sufficient": False, "loop_count": 3, "max_loops": 3}, "write_report"),
        ({"is_sufficient": False, "loop_count": 1, "max_loops": 1}, "write_report"),
    ],
)
def test_route_after_evaluate(state, expected):
    assert route_after_evaluate(state) == expected


def test_fan_out_one_send_per_task():
    sends = fan_out({"pending_queries": TASKS})
    assert [s.node for s in sends] == ["search", "search"] and sends[1].arg == TASKS[1]
