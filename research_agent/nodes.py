import logging
import os
import time
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from research_agent.prompts import (
    EVALUATE_PROMPT,
    FOLLOWUP_PROMPT,
    PLAN_PROMPT,
    REPORT_PROMPT,
)
from research_agent.state import SearchState, State

load_dotenv()
log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# [4] OpenAI 호출: 실패 시 자동 재시도 + 타임아웃
_llm_opts = dict(temperature=0, max_retries=3, timeout=60)
llm = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), **_llm_opts)
eval_llm = ChatOpenAI(model=os.getenv("EVAL_MODEL", "gpt-4o"), **_llm_opts)
report_llm = ChatOpenAI(
    model=os.getenv("REPORT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini")), **_llm_opts
)
search_tool = TavilySearch(max_results=_env_int("SEARCH_MAX_RESULTS", 3))

MIN_DOMAINS = _env_int("MIN_DOMAINS", 3)
MIN_RESULTS_PER_SUBQ = _env_int("MIN_RESULTS_PER_SUBQ", 2)
# [3] 토큰 관리: 결과 본문 길이 + 하위 질문당 프롬프트에 넣을 결과 수 제한
MAX_CONTENT_CHARS = _env_int("MAX_CONTENT_CHARS", 800)
MAX_RESULTS_PER_SUBQ_IN_PROMPT = _env_int("MAX_RESULTS_PER_SUBQ_IN_PROMPT", 4)
SEARCH_RETRIES = _env_int("SEARCH_RETRIES", 2)


# ---------- 공통 유틸 ----------
def _today() -> str:
    # [2] 로컬 시간 기준 오늘 날짜 (tz 데이터베이스 없이 동작)
    now = datetime.now().astimezone()
    return now.strftime("%Y년 %m월 %d일")


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {q}" for i, q in enumerate(items, 1))


def _select(state: State) -> list[dict]:
    """[1][3] 프롬프트에 넣을 결과를 고른다.
    - 현재 하위 질문의 결과만 (후속 질문 때 이전 라운드 결과 제외)
    - URL 중복 제거, 하위 질문당 최대 N건
    - 하위 질문 순서 → 수집 순서로 정렬해 항상 같은 번호가 나오게 함
    이 목록의 순서가 곧 보고서의 [번호]이자 sources의 번호다.
    """
    subs = state.get("sub_questions", [])
    seen, picked = set(), {q: [] for q in subs}
    for r in state.get("results", []):
        q = r.get("sub_question")
        url = r.get("url")
        if q not in picked or not url or url in seen:
            continue
        if len(picked[q]) >= MAX_RESULTS_PER_SUBQ_IN_PROMPT:
            continue
        seen.add(url)
        picked[q].append(r)
    return [r for q in subs for r in picked[q]]


def _format_results(results: list[dict]) -> str:
    lines = [
        f"[{i}] {r.get('title', '')}\nURL: {r.get('url', '')}\n"
        f"(하위 질문: {r.get('sub_question', '')})\n{r.get('content', '')}\n"
        for i, r in enumerate(results, 1)
    ]
    return "\n".join(lines) if lines else "(없음)"



# ---------- plan: 질문을 하위 질문으로 쪼개기 ----------
class PlanItem(BaseModel):
    sub_question: str = Field(description="조사할 하위 질문")
    query: str = Field(description="이 하위 질문용 웹 검색어")


class Plan(BaseModel):
    items: list[PlanItem] = Field(description="하위 질문 3~4개")


def plan(state: State) -> dict:
    past = state.get("past_questions", [])
    prev_report = (state.get("report") or "")[:1000] or "(없음)"
    result = llm.with_structured_output(Plan).invoke(
        PLAN_PROMPT.format(
            today=_today(),
            question=state["question"],
            past_questions=" / ".join(past) or "(없음)",
            previous_report=prev_report,
        )
    )
    items = result.items[:4]
    return {
        "past_questions": [state["question"]],
        "sub_questions": [it.sub_question for it in items],
        "pending_queries": [{"query": it.query, "sub_question": it.sub_question} for it in items],
        "loop_count": 1,
        # 새 질문이 시작되면 이전 평가/보고서 상태는 초기화
        "covered": [],
        "rule_notes": [],
        "is_sufficient": False,
        "missing_info": "",
    }


# ---------- [6] review_plan: 검색 전에 사용자 승인/수정 (interrupt) ----------
def review_plan(state: State) -> dict:
    tasks = state.get("pending_queries", [])
    if state.get("review"):
        # 실행이 여기서 멈추고, Command(resume=...)로 값을 받으면 이 줄부터 다시 실행된다
        answer = interrupt(
            {
                "type": "review_plan",
                "message": "검색할 하위 질문을 확인하세요. 수정하거나 그대로 승인할 수 있어요.",
                "sub_questions": [t["sub_question"] for t in tasks],
                "queries": [t["query"] for t in tasks],
            }
        )
        edited = answer.get("sub_questions") if isinstance(answer, dict) else None
        if edited:
            by_sub = {t["sub_question"]: t["query"] for t in tasks}
            edited = [s.strip() for s in edited if s and s.strip()][:6]
            # 바뀌지 않은 하위 질문은 원래 검색어를, 새로 쓴 하위 질문은 그 문장을 검색어로 사용
            tasks = [{"sub_question": s, "query": by_sub.get(s, s)} for s in edited]
    return {
        "sub_questions": [t["sub_question"] for t in tasks],
        "pending_queries": tasks,
        "queries": [t["query"] for t in tasks],
    }


# ---------- 재검색: 근거가 없는 하위 질문만 다시 검색어 생성 ----------
class FollowUpItem(BaseModel):
    sub_question_no: int = Field(description="근거가 부족한 하위 질문 목록의 번호 (1부터)")
    query: str = Field(description="새 검색어")


class FollowUp(BaseModel):
    items: list[FollowUpItem] = Field(description="새 검색어 (최대 3개)")


def generate_query(state: State) -> dict:
    subs = state.get("sub_questions", [])
    covered = state.get("covered", [])
    uncovered = [q for q, ok in zip(subs, covered) if not ok] or subs
    result = llm.with_structured_output(FollowUp).invoke(
        FOLLOWUP_PROMPT.format(
            today=_today(),
            question=state["question"],
            uncovered=_numbered(uncovered),
            missing_info=state.get("missing_info") or "(없음)",
            queries=", ".join(state.get("queries", [])) or "(없음)",
        )
    )
    tasks = []
    for it in result.items[:3]:
        # 번호로 원래 하위 질문 문장에 정확히 연결 (LLM이 문장을 바꿔 써도 안전)
        idx = min(max(it.sub_question_no, 1), len(uncovered)) - 1
        tasks.append({"query": it.query, "sub_question": uncovered[idx]})
    return {
        "pending_queries": tasks,
        "queries": [t["query"] for t in tasks],
        "loop_count": state.get("loop_count", 0) + 1,
    }


# ---------- search: Send로 검색어마다 병렬 실행 ----------
def search(state: SearchState) -> dict:
    query = state["query"]
    last_error = None
    for attempt in range(SEARCH_RETRIES + 1):  # [4] 재시도
        try:
            response = search_tool.invoke({"query": query})
            break
        except Exception as e:  # noqa: BLE001
            last_error = e
            log.warning("search failed (%s/%s): %s", attempt + 1, SEARCH_RETRIES + 1, e)
            time.sleep(1.5 * (attempt + 1))
    else:
        # 끝내 실패하면 그래프를 멈추지 않고 빈 결과로 넘어간다 (평가에서 재검색 대상이 됨)
        return {"results": [], "search_errors": [f"'{query}': {last_error}"]}

    items = response.get("results", []) if isinstance(response, dict) else []
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "content": (r.get("content") or "")[:MAX_CONTENT_CHARS],  # [3]
            "query": query,
            "sub_question": state["sub_question"],
        }
        for r in items
    ]
    return {"results": results}


# ---------- evaluate: 강한 모델 + 규칙 점검 + 근거 기록 ----------
class Evaluation(BaseModel):
    covered: list[bool] = Field(description="하위 질문별 구체적 근거 여부 (같은 순서)")
    missing_info: str = Field(description="근거가 없는 하위 질문과 더 찾을 내용. 충분하면 빈 문자열")


def evaluate(state: State) -> dict:
    subs = state.get("sub_questions", [])
    selected = _select(state)

    result = eval_llm.with_structured_output(Evaluation).invoke(
        EVALUATE_PROMPT.format(
            today=_today(),
            question=state["question"],
            sub_questions=_numbered(subs),
            results=_format_results(selected),
        )
    )
    covered = (list(result.covered) + [False] * len(subs))[: len(subs)]

    notes: list[str] = []
    domains = {_domain(r["url"]) for r in selected}
    if len(domains) < MIN_DOMAINS:
        notes.append(f"출처 도메인 {len(domains)}개 (최소 {MIN_DOMAINS}개 필요)")
    for i, q in enumerate(subs):
        n = sum(1 for r in selected if r.get("sub_question") == q)
        if n < MIN_RESULTS_PER_SUBQ:
            covered[i] = False
            notes.append(f"'{q}' 검색 결과 {n}건 (최소 {MIN_RESULTS_PER_SUBQ}건 필요)")

    is_sufficient = bool(subs) and all(covered) and not notes
    missing = result.missing_info
    if notes:
        missing = (missing + " / " if missing else "") + "규칙 점검: " + "; ".join(notes)

    return {
        "covered": covered,
        "rule_notes": notes,
        "is_sufficient": is_sufficient,
        "missing_info": "" if is_sufficient else missing,
    }


# ---------- write_report: [1] 보고서와 같은 번호의 sources를 함께 반환 ----------
def write_report(state: State) -> dict:
    selected = _select(state)
    report = report_llm.invoke(
        REPORT_PROMPT.format(
            today=_today(),
            question=state["question"],
            sub_questions=_numbered(state.get("sub_questions", [])),
            missing_info=state.get("missing_info") or "(없음)",
            results=_format_results(selected),
        )
    ).content
    sources = [
        {"n": i, "title": r.get("title"), "url": r.get("url"), "sub_question": r.get("sub_question")}
        for i, r in enumerate(selected, 1)
    ]
    return {"report": report, "sources": sources}
