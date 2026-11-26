"""그래프 전체 흐름 테스트"""
import re

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import research_agent.nodes as n
from research_agent.graph import build_graph

from conftest import FAST, SearchStub


def test_full_flow_and_source_numbering(stubs):
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, FAST)
    assert out["loop_count"] == 2  # 1회 부족 → 재검색 1회
    assert [s["n"] for s in out["sources"]] == list(range(1, len(out["sources"]) + 1))
    used = {int(x) for x in re.findall(r"\[(\d+)\]", out["report"])}
    assert used <= {s["n"] for s in out["sources"]}
    order = [s["sub_question"] for s in out["sources"]]
    assert order == sorted(order, key=out["sub_questions"].index)
    assert all(len(r["content"]) <= n.DEFAULTS.max_content_chars for r in out["results"])
    assert any(r["query"] == "retry" and r["sub_question"] in out["sub_questions"] for r in out["results"])


def test_retry_results_reach_report(stubs):
    """재검색 결과가 보고서 출처에 실제로 들어간다"""
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, FAST)
    assert any(src["url"].startswith("https://retry") for src in out["sources"])
    assert {r["round"] for r in out["results"]} == {1, 2}


def test_no_plan_variant_runs(stubs):
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, {"configurable": {"use_plan": False, "max_loops": 1, "search_retries": 0}})
    assert out["sub_questions"] == ["Q"] and stubs["search"].calls == ["Q"] and out["report"]


def test_parallel_search_count(stubs):
    build_graph().invoke({"question": "Q", "loop_count": 0}, FAST)
    assert sorted(stubs["search"].calls) == ["q0", "q1", "q2", "retry"]


def test_max_loops_from_config(stubs):
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, {"configurable": {"max_loops": 1, "search_retries": 0}})
    assert out["loop_count"] == 1 and out["report"]  # 부족해도 1라운드에서 보고서


def test_review_interrupt_edit_and_followup(stubs):
    g = build_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1", "search_retries": 0}}
    events = list(g.stream({"question": "Q", "review": True, "loop_count": 0}, cfg, stream_mode="updates"))
    intr = [e for e in events if "__interrupt__" in e]
    assert intr and intr[0]["__interrupt__"][0].value["sub_questions"] == ["SQ0", "SQ1", "SQ2"]
    assert g.get_state(cfg).next == ("review_plan",)

    out = g.invoke(Command(resume={"sub_questions": ["SQ0", "NEW2", "EXTRA"]}), cfg)
    assert out["sub_questions"] == ["SQ0", "NEW2", "EXTRA"]
    assert "NEW2" in out["queries"] and "q0" in out["queries"]

    out2 = g.invoke({"question": "더 자세히", "review": False, "loop_count": 0}, cfg)
    assert out2["past_questions"] == ["Q", "더 자세히"]
    assert out2["report"] == "두번째 보고서 [1]"
    assert all(s["sub_question"] in out2["sub_questions"] for s in out2["sources"])
    # 후속 질문 plan 프롬프트에 이전 질문이 들어감
    assert any("이전 질문: Q" in p for p in stubs["llm"].prompts)


def test_search_failure_does_not_crash(stubs, monkeypatch):
    monkeypatch.setattr(n, "search_tool", SearchStub(fail_on={"q1"}))
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, FAST)
    assert out["search_errors"] and "q1" in out["search_errors"][0]
    assert out["report"]


def test_report_tokens_stream(stubs):
    g = build_graph()
    tokens = [
        chunk.content
        for mode, data in g.stream({"question": "Q", "loop_count": 0}, FAST, stream_mode=["updates", "messages"])
        if mode == "messages"
        for chunk, meta in [data]
        if meta.get("langgraph_node") == "write_report"
    ]
    assert "".join(tokens).startswith("요약") and len(tokens) > 1


def test_verify_step_fixes_unsupported_number(stubs, monkeypatch):
    """보고서에 근거 없는 수치가 있으면 verify_report가 고친 보고서로 바꾼다"""
    from conftest import fake_report
    monkeypatch.setattr(n, "report_llm", fake_report("총 투자액은 2,450억 원이다 [1].", "총 투자액은 검색 결과로 확인되지 않음 [1]."))
    g = build_graph()
    nodes = [k for upd in g.stream({"question": "Q", "loop_count": 0}, FAST, stream_mode="updates") for k in upd]
    assert nodes[-2:] == ["write_report", "verify_report"]
    out = build_graph().invoke({"question": "Q", "loop_count": 0}, FAST)
    assert "2,450" not in out["report"] and out["revised_sentences"] == 1
