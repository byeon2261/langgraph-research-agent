from langgraph.graph import END, START, StateGraph

from research_agent.nodes import evaluate, generate_query, search, write_report
from research_agent.state import State

MAX_LOOPS = 3


def route_after_evaluate(state: State) -> str:
    if state["is_sufficient"] or state["loop_count"] >= MAX_LOOPS:
        return "write_report"
    return "generate_query"


builder = StateGraph(State)
builder.add_node("generate_query", generate_query)
builder.add_node("search", search)
builder.add_node("evaluate", evaluate)
builder.add_node("write_report", write_report)

builder.add_edge(START, "generate_query")
builder.add_edge("generate_query", "search")
builder.add_edge("search", "evaluate")
builder.add_conditional_edges(
    "evaluate", route_after_evaluate, ["generate_query", "write_report"]
)
builder.add_edge("write_report", END)

graph = builder.compile()
