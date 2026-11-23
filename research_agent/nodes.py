import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from pydantic import BaseModel, Field

from research_agent.prompts import EVALUATE_PROMPT, QUERY_PROMPT, REPORT_PROMPT
from research_agent.state import State

load_dotenv()

llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
search_tool = TavilySearch(max_results=int(os.getenv("SEARCH_MAX_RESULTS", "3")))


def _format_results(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title', '')}\nURL: {r.get('url', '')}\n{r.get('content', '')}\n")
    return "\n".join(lines) if lines else "(없음)"


def generate_query(state: State) -> dict:
    prompt = QUERY_PROMPT.format(
        question=state["question"],
        queries=", ".join(state.get("queries", [])) or "(없음)",
        missing_info=state.get("missing_info") or "(처음 검색)",
    )
    query = llm.invoke(prompt).content.strip().strip('"')
    return {"queries": [query], "loop_count": state.get("loop_count", 0) + 1}


def search(state: State) -> dict:
    query = state["queries"][-1]
    response = search_tool.invoke({"query": query})
    items = response.get("results", []) if isinstance(response, dict) else []
    results = [
        {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
        for r in items
    ]
    return {"results": results}


class Evaluation(BaseModel):
    required_info: list[str] = Field(description="질문에 답하는 데 필요한 정보 항목 3~5개")
    covered: list[bool] = Field(description="required_info 각 항목에 구체적 근거가 있으면 true (같은 순서)")
    is_sufficient: bool = Field(description="모든 항목이 covered일 때만 true")
    missing_info: str = Field(description="근거가 없는 항목과 다음에 찾을 내용. 충분하면 빈 문자열")


def evaluate(state: State) -> dict:
    evaluator = llm.with_structured_output(Evaluation)
    result = evaluator.invoke(
        EVALUATE_PROMPT.format(
            question=state["question"], results=_format_results(state["results"])
        )
    )
    # LLM이 is_sufficient를 너그럽게 줘도, 항목 하나라도 빠졌으면 false로 처리
    is_sufficient = result.is_sufficient and bool(result.covered) and all(result.covered)
    return {"is_sufficient": is_sufficient, "missing_info": result.missing_info}


def write_report(state: State) -> dict:
    report = llm.invoke(
        REPORT_PROMPT.format(
            question=state["question"], results=_format_results(state["results"])
        )
    ).content
    return {"report": report}
