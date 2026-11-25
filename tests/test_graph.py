"""가짜 LLM/검색으로 그래프 흐름을 검증한다 (API 키 불필요). uv run pytest"""
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("TAVILY_API_KEY", "tvly-test")

import re

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import research_agent.nodes as n
from research_agent.graph import build_graph


class StructuredStub:
    """with_structured_output만 흉내 내는 가짜 LLM"""

    def __init__(self, handler, schema=None):
        self.handler, self.schema = handler, schema

    def with_structured_output(self, schema):
        return StructuredStub(self.handler, schema)

    def invoke(self, prompt):
        return self.handler(self.schema.__name__, prompt)


def default_handler(state):
    def handler(name, prompt):
        if name == "Plan":
            return n.Plan(items=[n.PlanItem(sub_question=f"SQ{i}", query=f"q{i}") for i in range(3)])
        if name == "FollowUp":
            return n.FollowUp(items=[n.FollowUpItem(sub_question_no=1, query="retry")])
        if name == "Evaluation":
            state["eval"] += 1
            return n.Evaluation(covered=[True, True, state["eval"] > 1], missing_info="")
        raise AssertionError(name)
    return handler


class SearchStub:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)

    def invoke(self, args):
        q = args["query"]
        if q in self.fail_on:
            raise RuntimeError("tavily down")
        return {"results": [{"title": f"{q}-{k}", "url": f"https://{q}{k}.com/x", "content": "c" * 5000} for k in range(2)]}


@pytest.fixture
def setup(monkeypatch):
    st = {"eval": 0}
    monkeypatch.setattr(n, "llm", StructuredStub(default_handler(st)))
    monkeypatch.setattr(n, "eval_llm", StructuredStub(default_handler(st)))
    monkeypatch.setattr(n, "report_llm", GenericFakeChatModel(messages=iter([AIMessage(content="요약 [1] 그리고 [4]"), AIMessage(content="두번째 보고서 [1]")])))
    monkeypatch.setattr(n, "search_tool", SearchStub())
    monkeypatch.setattr(n, "SEARCH_RETRIES", 0)
    monkeypatch.setattr(n.time, "sleep", lambda s: None)
    return st


def test_full_flow_and_source_numbering(setup):
    g = build_graph()
    out = g.invoke({"question": "Q", "loop_count": 0})
    assert out["loop_count"] == 2  # 1회 부족 → 재검색 1회
    assert [s["n"] for s in out["sources"]] == list(range(1, len(out["sources"]) + 1))
    # 보고서에 쓰인 번호는 모두 sources 범위 안
    used = {int(x) for x in re.findall(r"\[(\d+)\]", out["report"])}
    assert used <= {s["n"] for s in out["sources"]}
    # 하위 질문 순서대로 정렬되어 있음
    order = [s["sub_question"] for s in out["sources"]]
    assert order == sorted(order, key=lambda q: out["sub_questions"].index(q))
    # 본문 길이 제한
    assert all(len(r["content"]) <= n.MAX_CONTENT_CHARS for r in out["results"])
    # 재검색 결과가 정확한 하위 질문 문장에 연결됨
    assert any(r["query"] == "retry" and r["sub_question"] in out["sub_questions"] for r in out["results"])


def test_review_interrupt_edit_and_followup(setup):
    g = build_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    events = list(g.stream({"question": "Q", "review": True, "loop_count": 0}, cfg, stream_mode="updates"))
    intr = [e for e in events if "__interrupt__" in e]
    assert intr and intr[0]["__interrupt__"][0].value["sub_questions"] == ["SQ0", "SQ1", "SQ2"]
    assert g.get_state(cfg).next == ("review_plan",)

    # SQ1 삭제, SQ2 수정, 새 항목 추가
    out = g.invoke(Command(resume={"sub_questions": ["SQ0", "NEW2", "EXTRA"]}), cfg)
    assert out["sub_questions"] == ["SQ0", "NEW2", "EXTRA"]
    assert "NEW2" in out["queries"] and "q0" in out["queries"]

    # 같은 thread에서 후속 질문: 이전 질문이 맥락으로 남음
    out2 = g.invoke({"question": "더 자세히", "review": False, "loop_count": 0}, cfg)
    assert out2["past_questions"] == ["Q", "더 자세히"]
    assert out2["report"] == "두번째 보고서 [1]"
    # 후속 질문의 sources는 이번 하위 질문 결과만
    assert all(s["sub_question"] in out2["sub_questions"] for s in out2["sources"])


def test_search_failure_does_not_crash(setup, monkeypatch):
    monkeypatch.setattr(n, "search_tool", SearchStub(fail_on={"q1"}))
    out = build_graph().invoke({"question": "Q", "loop_count": 0})
    assert out["search_errors"] and "q1" in out["search_errors"][0]
    assert out["report"]


def test_report_tokens_stream(setup):
    g = build_graph()
    tokens = [
        c.content
        for mode, (c, meta) in (
            (m, d) for m, d in g.stream({"question": "Q", "loop_count": 0}, stream_mode=["updates", "messages"]) if m == "messages"
        )
        if meta.get("langgraph_node") == "write_report"
    ]
    assert "".join(tokens).startswith("요약")
    assert len(tokens) > 1  # 여러 조각으로 나뉘어 도착
