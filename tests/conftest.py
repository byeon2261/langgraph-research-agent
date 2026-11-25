"""공통 테스트 도구: 가짜 LLM / 가짜 검색 (API 키 불필요)"""
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("TAVILY_API_KEY", "tvly-test")

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import research_agent.nodes as n


class StructuredStub:
    """with_structured_output(...).invoke(...)만 흉내 내는 가짜 LLM.
    handler(schema_name, prompt) -> pydantic 객체"""

    def __init__(self, handler, schema=None):
        self.handler, self.schema = handler, schema
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        child = StructuredStub(self.handler, schema)
        child.prompts = self.prompts
        return child

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.handler(self.schema.__name__, prompt)


def make_handler(counter, n_subq=3, fail_first_eval=True):
    def handler(name, prompt):
        if name == "Plan":
            return n.Plan(items=[n.PlanItem(sub_question=f"SQ{i}", query=f"q{i}") for i in range(n_subq)])
        if name == "FollowUp":
            return n.FollowUp(items=[n.FollowUpItem(sub_question_no=1, query="retry")])
        if name == "Evaluation":
            counter["eval"] += 1
            last_ok = (counter["eval"] > 1) or not fail_first_eval
            return n.Evaluation(covered=[True] * (n_subq - 1) + [last_ok], missing_info="")
        raise AssertionError(name)

    return handler


class SearchStub:
    """검색어마다 서로 다른 도메인 2건을 돌려주는 가짜 검색"""

    def __init__(self, fail_on=(), per_query=2):
        self.fail_on, self.per_query = set(fail_on), per_query
        self.calls: list[str] = []

    def invoke(self, args):
        q = args["query"]
        self.calls.append(q)
        if q in self.fail_on:
            raise RuntimeError("tavily down")
        return {
            "results": [
                {"title": f"{q}-{k}", "url": f"https://{q}{k}.example.com/x", "content": "c" * 5000}
                for k in range(self.per_query)
            ]
        }


def fake_report(*texts):
    texts = texts or ("요약 [1] 그리고 [2]",)
    return GenericFakeChatModel(messages=iter([AIMessage(content=t) for t in texts] * 20))


@pytest.fixture
def stubs(monkeypatch):
    """기본 가짜 세트. 필요하면 테스트에서 속성을 바꿔 쓴다."""
    counter = {"eval": 0}
    llm = StructuredStub(make_handler(counter))
    monkeypatch.setattr(n, "llm", llm)
    monkeypatch.setattr(n, "eval_llm", llm)
    monkeypatch.setattr(n, "report_llm", fake_report("요약 [1] 그리고 [4]", "두번째 보고서 [1]"))
    search = SearchStub()
    monkeypatch.setattr(n, "search_tool", search)
    monkeypatch.setattr(n.time, "sleep", lambda s: None)
    # 기본값이 아닌 모델 이름이 와도 실제 OpenAI를 부르지 않도록
    monkeypatch.setattr(n, "_chat", lambda model: llm)
    return {"counter": counter, "llm": llm, "search": search}


# 테스트용 실행 설정: 검색 재시도 없음
FAST = {"configurable": {"search_retries": 0}}
