from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from research_agent.nodes import (
    DEFAULTS,
    evaluate,
    generate_query,
    plan,
    review_plan,
    search,
    write_report,
)
from research_agent.state import State

# [4] 구조화 출력 파싱 실패 같은 일시적 오류는 노드 단위로 한 번 더 시도
_retry = RetryPolicy(max_attempts=2)


def fan_out(state: State) -> list[Send]:
    """pending_queries마다 search 노드를 하나씩 병렬로 실행"""
    return [Send("search", t) for t in state.get("pending_queries", [])]


def route_after_evaluate(state: State) -> str:
    max_loops = state.get("max_loops") or DEFAULTS.max_loops
    if state["is_sufficient"] or state["loop_count"] >= max_loops:
        return "write_report"
    return "generate_query"


def build_graph(checkpointer=None):
    builder = StateGraph(State)
    builder.add_node("plan", plan, retry_policy=_retry)
    builder.add_node("review_plan", review_plan)  # interrupt 노드 (재시도 X)
    builder.add_node("generate_query", generate_query, retry_policy=_retry)
    builder.add_node("search", search)
    builder.add_node("evaluate", evaluate, retry_policy=_retry)
    builder.add_node("write_report", write_report, retry_policy=_retry)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "review_plan")
    builder.add_conditional_edges("review_plan", fan_out, ["search"])
    builder.add_conditional_edges("generate_query", fan_out, ["search"])
    # 병렬 search가 모두 끝나면 evaluate가 한 번 실행된다 (fan-in)
    builder.add_edge("search", "evaluate")
    builder.add_conditional_edges(
        "evaluate", route_after_evaluate, ["generate_query", "write_report"]
    )
    builder.add_edge("write_report", END)
    return builder.compile(checkpointer=checkpointer)


# langgraph dev / LangGraph 서버용: 서버가 체크포인터(스레드 저장)를 자동으로 붙여 준다
graph = build_graph()
